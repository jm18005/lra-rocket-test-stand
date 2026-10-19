"""Upload a .ded model to a local Stabileo app, solve it, and collect results."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
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


class StabileoSession:
    """Manages a persistent browser session for fast iterative solves."""

    def __init__(
        self,
        *,
        app_url: str = "http://localhost:4000/",
        timeout_ms: int = 120_000,
        headless: bool = True,
    ) -> None:
        self.app_url = app_url
        self.timeout_ms = timeout_ms
        self.headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._file_input: Any = None
        self._solve_button: Any = None

    def start(self) -> StabileoSession:
        from playwright.sync_api import sync_playwright  # noqa: 13

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        self._page.goto(self.app_url, wait_until="domcontentloaded")

        cta = self._page.get_by_role("button", name="Open the editor")
        if cta.count() and cta.first.is_visible():
            cta.first.click()

        self._file_input = self._page.locator('input[type="file"][accept=".ded,.json"]').first
        self._file_input.wait_for(state="attached")
        self._solve_button = self._page.locator('[data-testid="rb-cmd-solve"]')
        self._solve_button.wait_for(state="visible")
        return self

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def __enter__(self) -> StabileoSession:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def solve(
        self,
        ded_file: str | Path,
        *,
        include_buckling: bool = False,
        include_pdelta: bool = False,
        extract_html_tables: bool = False,
        output_file: str | Path | None = None,
    ) -> dict[str, Any]:
        source = Path(ded_file).expanduser().resolve()
        if source.suffix.lower() != ".ded":
            raise ValueError(f"Expected a .ded file, got: {source}")
        if not source.is_file():
            raise FileNotFoundError(f".ded file does not exist: {source}")

        model = json.loads(source.read_text(encoding="utf-8"))
        self._file_input.set_input_files(str(source))

        if self._solve_button.is_disabled():
            raise RuntimeError(
                "Stabileo did not enable Solve after loading the .ded file. "
                "Check that the model contains nodes, members, supports, and loads."
            )

        self._solve_button.click()
        result_tabs = self._page.locator(".results-sub-tabs button")
        result_tabs.first.wait_for(state="visible", timeout=self.timeout_ms)

        extracted_results: list[dict[str, Any]] = []
        if extract_html_tables:
            case_selector = self._page.locator("#results-case")
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

            for case in cases:
                if case["value"]:
                    case_selector.select_option(case["value"])

                tab_count = result_tabs.count()
                for tab_index in range(tab_count):
                    tab = result_tabs.nth(tab_index)
                    tab_label = tab.inner_text().strip()
                    tab.click()
                    tab.wait_for(state="visible")
                    table_data = self._page.locator(".results-content table").evaluate_all(
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

        self._page.locator('[data-testid="hdr-project"]').click()
        with self._page.expect_download(timeout=self.timeout_ms) as download_info:
            self._page.get_by_role("button", name="CSV", exact=True).click()
        csv_download = download_info.value
        csv_path = csv_download.path()
        if csv_path is None:
            raise RuntimeError("Stabileo's results CSV download has no local file.")
        results_csv = Path(csv_path).read_text(encoding="utf-8")

        pdelta_data: dict[str, Any] | None = None
        buckling_data: dict[str, Any] | None = None

        if include_pdelta or include_buckling:
            adv_cmd = self._page.locator('[data-testid="rb-cmd-advanced"]')
            adv_cmd.click()
            self._page.locator(".advanced-grid").wait_for(state="visible")

            if include_pdelta:
                pdelta_btn = self._page.locator('.advanced-grid .adv-btn').filter(has_text="P-").first
                pdelta_btn.click()
                self._page.locator('[data-testid="pdelta-result"]').wait_for(state="visible")
                pd_raw = self._page.locator('[data-testid="pdelta-result"]').inner_text().strip()
                b2_match = re.search(r"B[₂2]\s*=\s*([0-9]+(?:\.[0-9]+)?)", pd_raw)
                iter_match = re.search(r"(\d+)\s*iter", pd_raw)
                pdelta_data = {
                    "raw": pd_raw,
                    "b2_factor": float(b2_match.group(1)) if b2_match else None,
                    "iterations": int(iter_match.group(1)) if iter_match else None,
                    "is_stable": "stable" in pd_raw.lower() and "unstable" not in pd_raw.lower(),
                }
                self._page.locator('[data-testid="adv-close"]').click()
                self._page.locator(".advanced-grid").wait_for(state="visible")

            if include_buckling:
                buckling_btn = self._page.locator('.advanced-grid .adv-btn').filter(has_text="Pcr").first
                buckling_btn.click()
                self._page.locator(".adv-result-info").first.wait_for(state="visible")
                bu_lines = self._page.locator(".adv-result-info").all_inner_texts()
                lambda_val: float | None = None
                keff_dict: dict[int, float] = {}
                for line in bu_lines:
                    l_match = re.search(r"(?:λ_cr|lambda_cr|λ|_cr)\s*=\s*([0-9]+(?:\.[0-9]+)?)", line)
                    if l_match:
                        lambda_val = float(l_match.group(1))
                    if "Keff:" in line:
                        for pair in re.findall(r"E(\d+)\s*=\s*([0-9]+(?:\.[0-9]+)?)", line):
                            keff_dict[int(pair[0])] = float(pair[1])
                buckling_data = {
                    "raw": bu_lines,
                    "lambda_cr": lambda_val,
                    "k_effective": keff_dict,
                }
                self._page.locator('[data-testid="adv-close"]').click()
                self._page.locator(".advanced-grid").wait_for(state="visible")

        result: dict[str, Any] = {
            "source_file": str(source),
            "app_url": self.app_url,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "solver_results": extracted_results,
            "solver_results_csv": results_csv,
            "parsed_solver_results_csv": _parse_results_csv(results_csv),
            "pdelta": pdelta_data,
            "buckling": buckling_data,
            "result_value_precision": "Rendered UI values; values may be rounded.",
            "solver_status_messages": self._page.locator(".toast").all_inner_texts(),
        }

        if output_file is not None:
            destination = Path(output_file).expanduser().resolve()
            result["output_file"] = str(destination)
            destination.write_text(
                json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False),
                encoding="utf-8",
            )
        return result


def is_working_config(
    analysis_results: dict[str, Any],
    member_to_bar: dict[int, dict[str, Any]],
    fos_yield: float = 2.0,
    fos_ultimate: float = 3.0,
    fos_buckling: float = 3.0,
    default_fu_mpa: float = 207.0,
) -> bool:
    # 1. P-Delta second-order stability
    pdelta = analysis_results.get("pdelta")
    if pdelta is not None and not pdelta.get("is_stable", True):
        return False

    # 2. Global elastic buckling load factor
    buckling = analysis_results.get("buckling")
    if buckling is not None:
        lambda_cr = buckling.get("lambda_cr")
        if lambda_cr is not None and lambda_cr < fos_buckling:
            return False

    # 3. Member stress and individual Euler buckling
    tables = analysis_results.get("parsed_solver_results_csv", [])
    forces_table = next((t for t in tables if t["name"] == "Internal Forces"), None)
    if forces_table is None:
        return False

    for row in forces_table["rows"]:
        elem_id = int(row["Member"])
        bar = member_to_bar.get(elem_id)
        if bar is None:
            continue

        a_m2 = float(bar["a_m2"])
        ix_m4 = float(bar["ix_m4"])
        iy_m4 = float(bar["iy_m4"])
        cz_m = float(bar.get("width_m", 0.04)) / 2.0
        cy_m = float(bar.get("height_m", 0.04)) / 2.0

        # Node i combined stress
        ni_n = abs(float(row["Ni (kN)"])) * 1e3
        myi_nm = abs(float(row["Myi (kN·m)"])) * 1e3
        mzi_nm = abs(float(row["Mzi (kN·m)"])) * 1e3
        term_axial_i = ni_n / a_m2
        term_bend_y_i = (myi_nm * cz_m) / iy_m4
        term_bend_z_i = (mzi_nm * cy_m) / ix_m4
        sigma_i_mpa = (term_axial_i + term_bend_y_i + term_bend_z_i) / 1e6

        # Node j combined stress
        nj_n = abs(float(row["Nj (kN)"])) * 1e3
        myj_nm = abs(float(row["Myj (kN·m)"])) * 1e3
        mzj_nm = abs(float(row["Mzj (kN·m)"])) * 1e3
        term_axial_j = nj_n / a_m2
        term_bend_y_j = (myj_nm * cz_m) / iy_m4
        term_bend_z_j = (mzj_nm * cy_m) / ix_m4
        sigma_j_mpa = (term_axial_j + term_bend_y_j + term_bend_z_j) / 1e6

        sigma_max_mpa = max(sigma_i_mpa, sigma_j_mpa)

        # Yield and ultimate stress limits
        fy_mpa = float(bar["fy_mpa"])
        fu_mpa = float(bar.get("fu_mpa", default_fu_mpa))
        if sigma_max_mpa > (fy_mpa / fos_yield):
            return False
        if sigma_max_mpa > (fu_mpa / fos_ultimate):
            return False

        # Member local Euler column buckling under compression
        ni_raw_kn = float(row["Ni (kN)"])
        nj_raw_kn = float(row["Nj (kN)"])
        p_comp_kn = max(-ni_raw_kn, -nj_raw_kn, 0.0)
        if p_comp_kn > 0.0:
            l_m = float(row["L (m)"])
            e_pa = float(bar["e_mpa"]) * 1e6
            i_min_m4 = min(ix_m4, iy_m4)
            num_euler = (math.pi**2) * e_pa * i_min_m4
            denom_euler = (l_m**2) * 1e3
            p_euler_kn = num_euler / denom_euler
            if (p_comp_kn * fos_buckling) > p_euler_kn:
                return False

    return True
