import ast
from typing import Any, Dict

import pytest

from ai_example_code.ded_to_openseespy import check_ded, make_openseespy_script


def make_ded_data(analysis_mode: str) -> Dict[str, Any]:
    node_i = {"id": 1, "x": 0, "y": 0}
    node_j = {"id": 2, "x": 1, "y": 0}
    element = {
        "id": 1,
        "type": "frame",
        "nodeI": 1,
        "nodeJ": 2,
        "materialId": 1,
        "sectionId": 1,
        "releaseI": {"my": False, "mz": False, "t": False},
        "releaseJ": {"my": False, "mz": False, "t": False},
    }
    material = {"id": 1, "name": "Steel", "e": 200000, "nu": 0.3, "rho": 78.5}
    section = {"id": 1, "name": "Section", "a": 0.01, "iy": 0.0001, "iz": 0.0001, "j": 0.0002}
    if analysis_mode == "3d":
        node_i["z"] = 0
        node_j["z"] = 0

    return {
        "analysisMode": analysis_mode,
        "axisConvention3D": "rightHand",
        "includeSelfWeight": False,
        "snapshot": {
            "nodes": [[1, node_i], [2, node_j]],
            "materials": [[1, material]],
            "sections": [[1, section]],
            "elements": [[1, element]],
            "supports": [[1, {"id": 1, "nodeId": 1, "type": "fixed"}]],
            "loads": [
                {
                    "type": "nodal" if analysis_mode == "2d" else "nodal3d",
                    "data": {"id": 1, "nodeId": 2, "fx": 0, "fz": -1, "my": 0, "caseId": 1},
                }
            ],
            "loadCases": [{"id": 1, "name": "Dead", "type": "D"}],
            "combinations": [],
            "plates": [],
            "quads": [],
            "constraints": [],
            "connectors": [],
            "footings": [],
        },
    }


@pytest.mark.parametrize("analysis_mode", ["2d", "3d"])
def test_generated_openseespy_script_has_valid_python(analysis_mode: str) -> None:
    ded_data = make_ded_data(analysis_mode)

    check_ded(ded_data)
    script = make_openseespy_script(ded_data)

    ast.parse(script)
    assert '"elasticBeamColumn"' in script
    assert "-beamUniform" in script


def test_converter_rejects_released_frames() -> None:
    ded_data = make_ded_data("2d")
    ded_data["snapshot"]["elements"][0][1]["releaseI"]["my"] = True

    with pytest.raises(ValueError, match="end releases"):
        check_ded(ded_data)


def test_converter_rejects_shell_elements() -> None:
    ded_data = make_ded_data("3d")
    ded_data["snapshot"]["plates"].append([1, {"id": 1}])

    with pytest.raises(ValueError, match="plates"):
        check_ded(ded_data)


def test_generated_script_includes_independent_design_factors() -> None:
    script = make_openseespy_script(
        make_ded_data("2d"),
        yield_factor_of_safety=1.5,
        buckling_factor_of_safety=2.0,
    )

    assert "YIELD_FACTOR_OF_SAFETY = 1.5" in script
    assert "BUCKLING_FACTOR_OF_SAFETY = 2.0" in script
    assert '"PDelta"' in script
    assert '"member_checks"' in script


def test_generated_script_rejects_nonpositive_design_factor() -> None:
    with pytest.raises(ValueError, match="yield_factor_of_safety"):
        make_openseespy_script(make_ded_data("2d"), yield_factor_of_safety=0)
