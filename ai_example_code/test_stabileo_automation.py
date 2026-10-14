from pathlib import Path

import pytest

from stabileo_automation import _parse_results_csv, run_stabileo_analysis


def test_analysis_rejects_non_ded_file(tmp_path: Path) -> None:
    model_file = tmp_path / "model.json"
    model_file.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected a .ded file"):
        run_stabileo_analysis(model_file)


def test_analysis_reports_missing_ded_file(tmp_path: Path) -> None:
    model_file = tmp_path / "missing.ded"

    with pytest.raises(FileNotFoundError, match=".ded file does not exist"):
        run_stabileo_analysis(model_file)


def test_results_csv_is_parsed_into_numeric_sections() -> None:
    csv_text = """# Stabileo results
# project: frame
# date: 10/7/2026, 10:32:05 PM

# Displacements
Node,ux (m),uy (m)
1,0.125,0

# Reactions
Node,Fx (kN)
2,3.4
"""

    sections = _parse_results_csv(csv_text)

    assert sections == [
        {
            "name": "Displacements",
            "columns": ["Node", "ux (m)", "uy (m)"],
            "rows": [{"Node": 1, "ux (m)": 0.125, "uy (m)": 0}],
        },
        {
            "name": "Reactions",
            "columns": ["Node", "Fx (kN)"],
            "rows": [{"Node": 2, "Fx (kN)": 3.4}],
        },
    ]
