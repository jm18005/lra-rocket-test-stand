"""Upload a .ded model to a local Stabileo app, solve it, and collect results."""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_csv_value(value: str) -> int | float | str:
    try:
        number = float(value)
    except ValueError:
        return value
    if not math.isfinite(number):
        return value
    return int(number) if number.is_integer() else number


def _parse_results_csv(text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    metadata_comments = 0
    active_section: dict[str, Any] | None = None
    headers: list[str] | None = None

    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if row[0].startswith("#"):
            metadata_comments += 1
            if metadata_comments > 3:
                active_section = {"name": row[0].lstrip("# ").strip(), "rows": []}
                sections.append(active_section)
                headers = None
            continue
        if active_section is None:
            continue
        if headers is None:
            headers = row
            active_section["columns"] = headers
            continue
        if len(row) != len(headers):
            raise ValueError(
                f"Results CSV section {active_section['name']!r} has a row "
                f"with {len(row)} fields; expected {len(headers)}."
            )
        active_section["rows"].append(
            dict(zip(headers, (_parse_csv_value(value) for value in row), strict=True))
        )

    return sections


def run_stabileo_analysis(
    ded_file: str | Path,
    *,
    app_url: str = "http://localhost:4000/",
    output_file: str | Path | None = None,
    timeout_ms: int = 120_000,
    headless: bool = True,
) -> dict[str, Any]:
    """Upload and solve one .ded file, returning the input and visible result tables.

    The returned model is the complete JSON from the .ded file. Solver results
    are collected from Stabileo's Results panel for every available load case,
    combination, and result tab. Table values are the values rendered by the
    UI, so they may be rounded for display.
    """
    source = Path(ded_file).expanduser().resolve()
    if source.suffix.lower() != ".ded":
        raise ValueError(f"Expected a .ded file, got: {source}")
    if not source.is_file():
        raise FileNotFoundError(f".ded file does not exist: {source}")

    model = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(model, dict):
        raise ValueError(f".ded file must contain a JSON object: {source}")

    # Keep the browser dependency optional until an actual solve is requested.
    from playwright.sync_api import sync_playwright  # noqa: 13

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(app_url, wait_until="domcontentloaded")

            editor_cta = page.get_by_role("button", name="Open the editor")
            if editor_cta.count() and editor_cta.first.is_visible():
                editor_cta.first.click()

            file_input = page.locator('input[type="file"][accept=".ded,.json"]')
            file_input.wait_for(state="attached")
            file_input.set_input_files(str(source))

            solve_button = page.locator('[data-testid="rb-cmd-solve"]')
            solve_button.wait_for(state="visible")
            if solve_button.is_disabled():
                raise RuntimeError(
                    "Stabileo did not enable Solve after loading the .ded file. "
                    "Check that the model contains nodes, members, supports, and loads."
                )

            solve_button.click()
            result_tabs = page.locator(".results-sub-tabs button")
            result_tabs.first.wait_for(state="visible", timeout=timeout_ms)

            case_selector = page.locator("#results-case")
            cases: list[dict[str, str]] = []
            if case_selector.count():
                cases = case_selector.locator("option").evaluate_all(
                    """options => options.map(option => ({
                        value: option.value,
                        label: option.textContent.trim()
                    }))"""
                )
                cases = [case for case in cases if case["value"]]
            else:
                cases = [{"value": "", "label": "current"}]

            extracted_results: list[dict[str, Any]] = []
            for case in cases:
                if case["value"]:
                    case_selector.select_option(case["value"])

                tab_count = result_tabs.count()
                for tab_index in range(tab_count):
                    tab = result_tabs.nth(tab_index)
                    tab_label = tab.inner_text().strip()
                    tab.click()
                    tab.wait_for(state="visible")
                    table_data = page.locator(".results-content table").evaluate_all(
                        """tables => tables.map(table => ({
                            headers: Array.from(table.querySelectorAll('thead th'))
                                .map(cell => cell.innerText.trim()),
                            rows: Array.from(table.querySelectorAll('tbody tr'))
                                .map(row => Array.from(row.querySelectorAll('th, td'))
                                    .map(cell => cell.innerText.trim()))
                        }))"""
                    )
                    extracted_results.append(
                        {
                            "load_state": case["label"],
                            "load_state_value": case["value"],
                            "result_tab": tab_label,
                            "tables": table_data,
                        }
                    )

            page.locator('[data-testid="hdr-project"]').click()
            with page.expect_download(timeout=timeout_ms) as download_info:
                page.get_by_role("button", name="CSV", exact=True).click()
            csv_download = download_info.value
            csv_path = csv_download.path()
            if csv_path is None:
                raise RuntimeError("Stabileo's results CSV download has no local file.")
            results_csv = Path(csv_path).read_text(encoding="utf-8")

            result = {
                "source_file": str(source),
                "app_url": app_url,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "model": model,
                "solver_results": extracted_results,
                "solver_results_csv": results_csv,
                "parsed_solver_results_csv": _parse_results_csv(results_csv),
                "result_value_precision": "Rendered UI values; values may be rounded.",
                "solver_status_messages": page.locator(".toast").all_inner_texts(),
            }
            if not extracted_results:
                raise RuntimeError(
                    "Stabileo completed the Solve interaction, but no result tables "
                    "were found in its Results panel."
                )
            if output_file is not None:
                destination = Path(output_file).expanduser().resolve()
                result["output_file"] = str(destination)
                destination.write_text(
                    json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False),
                    encoding="utf-8",
                )
            return result
        finally:
            browser.close()


def main():
    run_stabileo_analysis(r"C:\Users\Josh\Downloads\3d_rocket_stand.ded", output_file=r"C:\Users\Josh\Downloads\res.json")


if __name__ == "__main__":
    main()