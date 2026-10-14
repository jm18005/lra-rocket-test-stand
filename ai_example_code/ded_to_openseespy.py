import json
import logging
import math
import sys
import warnings
from pathlib import Path
from typing import List, Optional, Union


def read_ded(filepath: Union[str, Path]) -> dict:
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def check_ded(ded_data: dict) -> None:
    snapshot = ded_data.get("snapshot", {})
    if not isinstance(snapshot, dict):
        raise ValueError("The .ded file does not have a valid snapshot.")

    analysis_mode = ded_data.get("analysisMode")
    if analysis_mode not in ("2d", "3d"):
        raise ValueError(f"Analysis mode {analysis_mode!r} is not supported.")
    if analysis_mode == "3d" and ded_data.get("axisConvention3D", "rightHand") != "rightHand":
        raise ValueError("Only the rightHand 3D axis convention is supported.")

    unsupported = ("plates", "quads", "constraints", "connectors", "footings")
    for key in unsupported:
        if snapshot.get(key):
            raise ValueError(f".ded {key} are not supported by this converter.")

    allowed_loads = ("nodal",) if analysis_mode == "2d" else ("nodal3d",)
    for load in snapshot.get("loads", []):
        if load.get("type") not in allowed_loads:
            raise ValueError(f"Load type {load.get('type')!r} is not supported.")

    material_ids = {record[0] for record in snapshot.get("materials", [])}
    section_ids = {record[0] for record in snapshot.get("sections", [])}
    for element_id, element in snapshot.get("elements", []):
        if element.get("type") not in ("frame", "truss"):
            raise ValueError(f"Element {element_id} type {element.get('type')!r} is not supported.")
        if element.get("materialId") not in material_ids:
            raise ValueError(f"Element {element_id} refers to a missing material.")
        if element.get("sectionId") not in section_ids:
            raise ValueError(f"Element {element_id} refers to a missing section.")
        for end in ("releaseI", "releaseJ"):
            if any(element.get(end, {}).values()):
                raise ValueError(f"Element {element_id} has end releases that are not supported.")


def get_conversion_warnings(ded_data: dict) -> List[str]:
    snapshot = ded_data["snapshot"]
    if ded_data["analysisMode"] != "3d":
        return []

    warnings_list = []
    sections = {}
    warned_sections = set()
    for element_id, element in snapshot.get("elements", []):
        if element.get("type") != "frame":
            continue
        section = sections.get(element["sectionId"])
        if section is None:
            section = next(
                record[1]
                for record in snapshot["sections"]
                if record[0] == element["sectionId"]
            )
            sections[element["sectionId"]] = section
        if "j" not in section and element["sectionId"] not in warned_sections:
            warnings_list.append(
                f"Section {section['name']!r} is missing J; using Iy + Iz "
                "as an approximate torsional constant."
            )
            warned_sections.add(element["sectionId"])
    return warnings_list


def make_openseespy_script(
    ded_data: dict,
    yield_factor_of_safety: float = 1.0,
    buckling_factor_of_safety: float = 1.0,
) -> str:
    if not math.isfinite(yield_factor_of_safety) or yield_factor_of_safety <= 0:
        raise ValueError("yield_factor_of_safety must be finite and greater than zero.")
    if not math.isfinite(buckling_factor_of_safety) or buckling_factor_of_safety <= 0:
        raise ValueError("buckling_factor_of_safety must be finite and greater than zero.")
    ded_text = json.dumps(ded_data, ensure_ascii=False, allow_nan=False)
    warnings_text = repr(get_conversion_warnings(ded_data))
    script = r'''import json
import math
from pathlib import Path

import openseespy.opensees as ops


DED_DATA = json.loads(__DED_JSON__)
MODEL_WARNINGS = __MODEL_WARNINGS__
YIELD_FACTOR_OF_SAFETY = __YIELD_FOS__
BUCKLING_FACTOR_OF_SAFETY = __BUCKLING_FOS__


def records(key):
    return [record[1] for record in DED_DATA["snapshot"].get(key, [])]


def get_by_id(key, idn):
    for record_id, record in DED_DATA["snapshot"][key]:
        if record_id == idn:
            return record
    raise ValueError(f"{idn} is not a valid id in {key}.")


def support_restraints(support, dimension):
    if dimension == 2:
        restraints = {
            "fixed": (1, 1, 1),
            "pinned": (1, 1, 0),
            "rollerX": (0, 1, 0),
            "rollerZ": (1, 0, 0),
        }
        if support["type"] not in restraints:
            raise ValueError(f"2D support type {support['type']!r} is not supported.")
        return restraints[support["type"]]

    if support.get("dofFrame", "global") != "global":
        raise ValueError(f"Support {support['id']} restraints are not in the global frame.")
    if "dofRestraints" in support:
        dofs = support["dofRestraints"]
        return tuple(int(dofs[key]) for key in ("tx", "ty", "tz", "rx", "ry", "rz"))
    restraints = {
        "fixed": (1, 1, 1, 1, 1, 1),
        "fixed3d": (1, 1, 1, 1, 1, 1),
        "pinned": (1, 1, 1, 0, 0, 1),
        "pinned3d": (1, 1, 1, 0, 0, 0),
        "custom3d": (1, 1, 1, 1, 1, 1),
        "rollerXZ": (0, 1, 0, 0, 0, 0),
        "rollerXY": (0, 0, 1, 0, 0, 0),
        "rollerYZ": (1, 0, 0, 0, 0, 0),
    }
    if support["type"] not in restraints:
        raise ValueError(f"3D support type {support['type']!r} is not supported.")
    return restraints[support["type"]]


def local_axes(node_i, node_j):
    start = get_by_id("nodes", node_i)
    end = get_by_id("nodes", node_j)
    vector = [end[key] - start[key] for key in ("x", "y", "z")]
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0:
        raise ValueError(f"Element from node {node_i} to {node_j} has zero length.")
    local_x = [value / length for value in vector]
    vec_xz = [0, 0, 1] if abs(local_x[2]) < 0.95 else [0, 1, 0]
    cross = (
        vec_xz[1] * local_x[2] - vec_xz[2] * local_x[1],
        vec_xz[2] * local_x[0] - vec_xz[0] * local_x[2],
        vec_xz[0] * local_x[1] - vec_xz[1] * local_x[0],
    )
    norm = math.sqrt(sum(value * value for value in cross))
    local_y = [value / norm for value in cross]
    local_z = [
        local_x[1] * local_y[2] - local_x[2] * local_y[1],
        local_x[2] * local_y[0] - local_x[0] * local_y[2],
        local_x[0] * local_y[1] - local_x[1] * local_y[0],
    ]
    return length, vec_xz, local_x, local_y, local_z


def add_model(load_factors):
    dimension = 2 if DED_DATA["analysisMode"] == "2d" else 3
    dofs = 3 if dimension == 2 else 6
    snapshot = DED_DATA["snapshot"]
    ops.wipe()
    ops.model("basic", "-ndm", dimension, "-ndf", dofs)

    for node in records("nodes"):
        if dimension == 2:
            ops.node(node["id"], node["x"], node["y"])
        else:
            ops.node(node["id"], node["x"], node["y"], node["z"])

    for support in records("supports"):
        restraints = support_restraints(support, dimension)
        ops.fix(support["nodeId"], *restraints)

    for material in records("materials"):
        ops.uniaxialMaterial("Elastic", material["id"], material["e"] * 1000)

    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)

    dead_cases = [
        case["id"]
        for case in snapshot.get("loadCases", [])
        if case.get("type") == "D"
    ]
    self_weight_factor = (
        sum(load_factors.get(case_id, 0) for case_id in dead_cases)
        if dead_cases
        else 1
    )

    for element_id, element in snapshot.get("elements", []):
        material = get_by_id("materials", element["materialId"])
        section = get_by_id("sections", element["sectionId"])
        elastic_modulus = material["e"] * 1000
        area = section["a"]

        if element["type"] == "truss":
            ops.element(
                "truss", element_id, element["nodeI"], element["nodeJ"],
                area, material["id"],
            )
        elif dimension == 2:
            ops.geomTransf("PDelta", element_id)
            ops.element(
                "elasticBeamColumn", element_id, element["nodeI"], element["nodeJ"],
                area, elastic_modulus, section.get("iy", section["iz"]), element_id,
            )
        else:
            _, vec_xz, _, _, _ = local_axes(element["nodeI"], element["nodeJ"])
            shear_modulus = elastic_modulus / (2 * (1 + material["nu"]))
            ops.geomTransf("PDelta", element_id, *vec_xz)
            ops.element(
                "elasticBeamColumn", element_id, element["nodeI"], element["nodeJ"],
                area, elastic_modulus, shear_modulus,
                section.get("j", section["iy"] + section["iz"]),
                section.get("iy", section["iz"]), section["iz"], element_id,
            )

        if DED_DATA.get("includeSelfWeight") and self_weight_factor:
            weight = material["rho"] * area * self_weight_factor
            if element["type"] == "truss":
                add_truss_weight(element, weight, dimension)
            elif dimension == 2:
                add_frame_weight_2d(element, weight)
            else:
                add_frame_weight_3d(element, weight)

    for load in snapshot.get("loads", []):
        data = load["data"]
        factor = load_factors.get(data.get("caseId"), 0)
        if not factor:
            continue
        if dimension == 2:
            ops.load(
                data["nodeId"], data.get("fx", 0) * factor,
                data.get("fz", 0) * factor, data.get("my", 0) * factor,
            )
        else:
            ops.load(
                data["nodeId"], data.get("fx", 0) * factor,
                data.get("fy", 0) * factor, data.get("fz", 0) * factor,
                data.get("mx", 0) * factor, data.get("my", 0) * factor,
                data.get("mz", 0) * factor,
            )


def add_truss_weight(element, weight, dimension):
    start = get_by_id("nodes", element["nodeI"])
    end = get_by_id("nodes", element["nodeJ"])
    keys = ("x", "y") if dimension == 2 else ("x", "y", "z")
    length = math.sqrt(sum((end[key] - start[key]) ** 2 for key in keys))
    vertical_index = 1 if dimension == 2 else 2
    load = [0] * dimension
    load[vertical_index] = -weight * length / 2
    ops.load(element["nodeI"], *load, *([0] if dimension == 2 else [0, 0, 0]))
    ops.load(element["nodeJ"], *load, *([0] if dimension == 2 else [0, 0, 0]))


def add_frame_weight_2d(element, weight):
    start = get_by_id("nodes", element["nodeI"])
    end = get_by_id("nodes", element["nodeJ"])
    dx = end["x"] - start["x"]
    dy = end["y"] - start["y"]
    length = math.sqrt(dx * dx + dy * dy)
    if length == 0:
        raise ValueError(f"Element {element['id']} has zero length.")
    local_x = (dx / length, dy / length)
    local_y = (-local_x[1], local_x[0])
    wx = -weight * local_x[1]
    wy = -weight * local_y[1]
    ops.eleLoad(
        "-ele", element["id"], "-type", "-beamUniform", wy, wx,
    )


def add_frame_weight_3d(element, weight):
    length, _, local_x, local_y, local_z = local_axes(element["nodeI"], element["nodeJ"])
    wy = -weight * local_y[2]
    wz = -weight * local_z[2]
    wx = -weight * local_x[2]
    ops.eleLoad(
        "-ele", element["id"], "-type", "-beamUniform", wy, wz, wx,
    )


def analyze(load_name, load_factors):
    add_model(load_factors)
    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.system("BandGeneral")
    ops.test("NormDispIncr", 1e-8, 10)
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 1)
    ops.analysis("Static")
    status = ops.analyze(1)
    if status != 0:
        raise RuntimeError(f"OpenSees analysis failed for {load_name!r}: {status}")

    ops.reactions()
    nodes = records("nodes")
    elements = records("elements")
    return {
        "load_state": load_name,
        "load_factors": load_factors,
        "analysis_order": "PDelta",
        "displacements": {
            str(node["id"]): ops.nodeDisp(node["id"])
            for node in nodes
        },
        "reactions": {
            str(node["id"]): ops.nodeReaction(node["id"])
            for node in nodes
        },
        "element_forces": {
            str(element["id"]): ops.eleForce(element["id"])
            for element in elements
        },
    }


def check_member_strength(element, forces):
    section = get_by_id("sections", element["sectionId"])
    material = get_by_id("materials", element["materialId"])
    dimension = 2 if DED_DATA["analysisMode"] == "2d" else 3
    start = get_by_id("nodes", element["nodeI"])
    end = get_by_id("nodes", element["nodeJ"])
    axes = ("x", "y") if dimension == 2 else ("x", "y", "z")
    length = math.sqrt(sum((end[key] - start[key]) ** 2 for key in axes))
    if length == 0:
        raise ValueError(f"Element {element['id']} has zero length.")

    if element["type"] == "truss":
        axial = max(abs(forces[0]), abs(forces[-1]))
        compression = max(0, (forces[0] - forces[-1]) / 2)
        moments = []
    elif dimension == 2:
        axial = max(abs(forces[0]), abs(forces[3]))
        compression = max(0, (forces[0] - forces[3]) / 2)
        moments = [(max(abs(forces[2]), abs(forces[5])), section.get("iz"), section.get("h"))]
    else:
        axial = max(abs(forces[0]), abs(forces[6]))
        compression = max(0, (forces[0] - forces[6]) / 2)
        moments = [
            (max(abs(forces[4]), abs(forces[10])), section.get("iy"), section.get("h")),
            (max(abs(forces[5]), abs(forces[11])), section.get("iz"), section.get("b")),
        ]

    axial_stress_mpa = axial / section["a"] / 1000
    fy = material.get("fy")
    axial_yield_fos = fy / axial_stress_mpa if fy and fy > 0 and axial_stress_mpa > 0 else None
    axial_yield_status = "NOT CHECKED"
    yield_fos = None
    yield_status = "NOT CHECKED"
    yield_basis = "axial_and_bending"
    combined_yield_checked = False
    stress_mpa = axial_stress_mpa
    if fy is not None and fy > 0:
        axial_yield_status = (
            "PASS" if axial_stress_mpa == 0 or axial_yield_fos >= YIELD_FACTOR_OF_SAFETY
            else "FAIL"
        )
        dimensions_available = element["type"] == "truss" or all(
            moment == 0 or (
                inertia is not None and inertia > 0 and depth is not None and depth > 0
            )
            for moment, inertia, depth in moments
        )
        if dimensions_available:
            combined_yield_checked = True
            for moment, inertia, depth in moments:
                if moment:
                    stress_mpa += moment * (depth / 2) / inertia / 1000
            yield_fos = fy / stress_mpa if stress_mpa > 0 else None
            yield_status = (
                "PASS" if stress_mpa == 0 or yield_fos >= YIELD_FACTOR_OF_SAFETY
                else "FAIL"
            )
        else:
            yield_basis = "axial_only_missing_section_dimensions"
            if axial_yield_status == "FAIL":
                yield_status = "FAIL"

    inertia_values = [
        value for value in (section.get("iy"), section.get("iz"))
        if value is not None and value > 0
    ]
    if dimension == 2:
        inertia = section.get("iz", section.get("iy"))
        inertia_values = [inertia] if inertia is not None and inertia > 0 else []
    buckling_fos = None
    buckling_capacity = None
    if compression > 0 and inertia_values and all(value > 0 for value in inertia_values):
        elastic_modulus = material["e"] * 1000
        buckling_capacity = math.pi ** 2 * elastic_modulus * min(inertia_values) / length ** 2
        buckling_fos = buckling_capacity / compression
        buckling_status = (
            "PASS" if buckling_fos >= BUCKLING_FACTOR_OF_SAFETY else "FAIL"
        )
    else:
        buckling_status = "PASS" if compression == 0 else "NOT CHECKED"

    return {
        "element_id": element["id"],
        "element_type": element["type"],
        "axial_demand_kN": axial,
        "compression_demand_kN": compression,
        "axial_stress_mpa": axial_stress_mpa,
        "maximum_normal_stress_mpa": stress_mpa if combined_yield_checked else None,
        "yield_strength_mpa": fy,
        "axial_yield_factor_of_safety": axial_yield_fos,
        "required_axial_yield_factor_of_safety": YIELD_FACTOR_OF_SAFETY,
        "axial_yield_status": axial_yield_status,
        "yield_factor_of_safety": yield_fos,
        "required_yield_factor_of_safety": YIELD_FACTOR_OF_SAFETY,
        "yield_check_basis": yield_basis,
        "yield_status": yield_status,
        "euler_buckling_capacity_kN": buckling_capacity,
        "buckling_factor_of_safety": buckling_fos,
        "required_buckling_factor_of_safety": BUCKLING_FACTOR_OF_SAFETY,
        "buckling_check_basis": "ideal_euler_column_pinned_pinned",
        "buckling_status": buckling_status,
    }


def add_design_checks(result):
    elements = records("elements")
    checks = [
        check_member_strength(element, result["element_forces"][str(element["id"])])
        for element in elements
    ]
    def combined_status(statuses):
        if "FAIL" in statuses:
            return "FAIL"
        if "NOT CHECKED" in statuses:
            return "NOT CHECKED"
        return "PASS"

    result["member_checks"] = checks
    result["axial_yield_status"] = combined_status(
        [check["axial_yield_status"] for check in checks]
    )
    result["yield_status"] = combined_status(
        [check["yield_status"] for check in checks]
    )
    result["buckling_status"] = combined_status(
        [check["buckling_status"] for check in checks]
    )
    result["configuration_status"] = combined_status(
        [result["yield_status"], result["buckling_status"]]
    )
    return result


def main():
    snapshot = DED_DATA["snapshot"]
    cases = snapshot.get("loadCases", [])
    states = []
    for case in cases:
        states.append((case["name"], {case["id"]: 1}))
    for combination in snapshot.get("combinations", []):
        factors = {
            item["caseId"]: item["factor"]
            for item in combination.get("factors", [])
        }
        states.append((combination["name"], factors))
    if not states:
        factors = {
            load["data"]["caseId"]: 1
            for load in snapshot.get("loads", [])
        }
        states.append(("All loads", factors))

    results = [
        add_design_checks(analyze(name, factors))
        for name, factors in states
    ]
    output = Path(__file__).with_suffix(".results.json")
    output.write_text(
        json.dumps(
            {
                "modeling_warnings": MODEL_WARNINGS,
                "design_basis": {
                    "yield_factor_of_safety": YIELD_FACTOR_OF_SAFETY,
                    "buckling_factor_of_safety": BUCKLING_FACTOR_OF_SAFETY,
                    "p_delta": True,
                    "buckling_method": "ideal Euler pinned-pinned column; no local buckling or code reductions",
                },
                "results": results,
            },
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    print(f"Results written to {output}")


if __name__ == "__main__":
    main()
'''
    return (
        script.replace("__DED_JSON__", repr(ded_text))
        .replace("__MODEL_WARNINGS__", warnings_text)
        .replace("__YIELD_FOS__", repr(yield_factor_of_safety))
        .replace("__BUCKLING_FOS__", repr(buckling_factor_of_safety))
    )


def convert_ded_to_openseespy(
    ded_file: Union[str, Path],
    output_file: Optional[Union[str, Path]] = None,
    yield_factor_of_safety: float = 1.0,
    buckling_factor_of_safety: float = 1.0,
) -> Path:
    ded_file = Path(ded_file)
    if not ded_file.is_file():
        raise FileNotFoundError(f".ded file does not exist: {ded_file}")
    ded_data = read_ded(ded_file)
    check_ded(ded_data)
    for warning in get_conversion_warnings(ded_data):
        warnings.warn(warning, RuntimeWarning)

    if output_file is None:
        output_file = ded_file.with_name(ded_file.stem + "_opensees.py")
    else:
        output_file = Path(output_file)

    script = make_openseespy_script(
        ded_data, yield_factor_of_safety, buckling_factor_of_safety
    )
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(script)
    return output_file


def main() -> int:
    if len(sys.argv) < 2:
        raise ValueError("Provide a .ded file to convert.")
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    yield_fos = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    buckling_fos = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    converted_file = convert_ded_to_openseespy(
        sys.argv[1], output_file, yield_fos, buckling_fos
    )
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.info("OpenSeesPy script written to %s", converted_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
