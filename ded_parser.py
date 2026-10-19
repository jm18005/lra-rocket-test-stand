import json
from beartype import beartype
import math

M2IN = 39.3700787

@beartype
def read_ded(filepath: str) -> dict:
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


@beartype
def get_new_id(ded_data: dict, id_name: str) -> int:
    idn = ded_data["snapshot"]["nextId"][id_name]
    ded_data["snapshot"]["nextId"][id_name] +=1
    return idn


@beartype
def add_material(ded_data: dict, name: str, e: float | int,
                 nu: float | int, rho: float | int, fy: float | int,
                 gradeId: str | None = None) -> int:

    idn = get_new_id(ded_data, "material")
    
    material = {
        "id"  : idn,
        "name": name,
        "e"   : e,
        "nu"  : nu,
        "rho" : rho,
        "fy"  : fy,
    }
    if gradeId is not None:
        material["gradeId"] = gradeId

    id_material = [idn, material]
    ded_data["snapshot"]["materials"].append(id_material)

    return idn


@beartype
def add_section(ded_data: dict, name: str, a: float | int, iz: float | int,
                iy: float | int, j: float | int, b: float | int | None = None,
                h: float | int | None = None, shape: str | None = None,
                t: float | int | None = None) -> int:

    idn = get_new_id(ded_data, "section")
    
    section = {
        "id"  : idn,
        "name": name,
        "a"   : a,
        "iz"  : iz,
        "iy"  : iy,
        "j"   : j,
    }

    if b is not None:
        section["b"] = b
    if h is not None:
        section["h"] = h
    if shape is not None:
        section["shape"] = shape
    if t is not None:
        section["t"] = t

    id_section = [idn, section]
    ded_data["snapshot"]["sections"].append(id_section)

    return idn


@beartype
def write_ded(ded_data: dict, output: str) -> None:
    if not output.endswith((".ded", "json")):
        raise ValueError("Please save with .ded/.json file extension")
    text = json.dumps(ded_data, indent=2, allow_nan=False)
    with open(output, "w", encoding="utf-8") as f:
        f.write(text)


@beartype
def get_id(obj: list) -> int:
    # works for elements, sections, supports, materials, nodes
    return obj[0]


@beartype
def get_name(obj: list) -> str:
    # works for sections, materials
    return obj[1]["name"]


@beartype
def get_name_from_id(ded_data: dict, idn: int, key: str) -> str:
    # works for sections, materials
    valid_keys = ['sections', 'materials']
    check_valid_keys(valid_keys, key)

    for obj in ded_data["snapshot"][key]:
        if obj[0] == idn:
            return obj[1]["name"]

    raise ValueError(f"Id {idn} is not in {key}")


@beartype
def get_id_from_name(ded_data: dict, name: str, key: str) -> int:
    # key is either "sections" or "materials"
    valid_keys = ['sections', 'materials']
    check_valid_keys(valid_keys, key)
    
    for obj in ded_data["snapshot"][key]:
        if obj[1]["name"] == name:
            return obj[0]

    raise ValueError(f"{name} is not in {key}")


@beartype
def check_valid_keys(valid_keys: list[str], key: str) -> None:
    if key not in valid_keys:
        raise ValueError(f"Key {key} must be in {valid_keys}")


@beartype
def find_by_id(ded_data: dict, idn: int, key: str) -> list:
    # works for elements, sections, supports, materials, nodes
    valid_keys = ['sections', 'materials', 'nodes', 'supports', 'elements']
    check_valid_keys(valid_keys, key)

    for obj in ded_data["snapshot"][key]:
        if get_id(obj) == idn:
            return obj

    raise ValueError(f"idn {idn} is not a valid id in {key}")


@beartype
def find_by_name(ded_data: dict, name: str, key: str) -> list:
    # key is either "sections" or "materials"
    valid_keys = ['sections', 'materials']
    check_valid_keys(valid_keys, key)


    for obj in ded_data["snapshot"][key]:
        if get_name(obj) == name:
            return obj

    raise ValueError(f"{name} is not a valid name in {key}")


@beartype
def assign_material(ded_data: dict, member_id: int, material_name: str | None = None,
                    material_id: int | None = None) -> None:
    if material_name is not None and material_id is not None:
        raise ValueError("Please provide only material_name or material_id.")
    if material_name is None and material_id is None:
        raise ValueError("Provide material_name or material_id.")
    
    member = find_by_id(ded_data, member_id, "elements")

    if material_name is not None:
        material_id = get_id_from_name(ded_data, material_name, "materials")

    member[1]["materialId"] = material_id


@beartype
def assign_section(ded_data: dict, member_id: int, section_name: str | None = None,
                   section_id: int | None = None) -> None:
    if section_name is not None and section_id is not None:
        raise ValueError("Please provide only section_name or section_id.")
    if section_name is None and section_id is None:
        raise ValueError("Provide section_name or section_id.")
    
    member = find_by_id(ded_data, member_id, "elements")

    if section_name is not None:
        section_id = get_id_from_name(ded_data, section_name, "sections")

    member[1]["sectionId"] = section_id


@beartype
def calc_member_len(ded_data: dict, member_id: int, unit_mult: int | float = 1) -> float:
    # calculates lengths in meters, apply unit_mult otherwise
    elem   = find_by_id(ded_data, member_id, "elements")[1]
    node_i = find_by_id(ded_data, elem["nodeI"], "nodes")[1]
    node_j = find_by_id(ded_data, elem["nodeJ"], "nodes")[1]

    dx = node_j["x"] - node_i["x"]
    dy = node_j["y"] - node_i["y"]
    dz = node_j.get("z", 0.0) - node_i.get("z", 0.0)
    return math.sqrt(dx**2 + dy**2 + dz**2) * unit_mult


@beartype
def calc_bar_cost(ded_data: dict, bar: dict, member_ids: list[int]) -> float:
    total_cost = 0
    for member_id in member_ids:
        length = calc_member_len(ded_data, member_id, unit_mult=M2IN)
        total_cost += bar["price_per_in_usd"] * length
    return total_cost


def assign_from_8020_profiles(ded_data: dict, bar: dict, member_ids: list[int], 
                              j_factor: float | int = 0.5, nu: float| int = 0.3) -> tuple[int]:
    # add material
    name = bar["part_number"]
    mat_id = add_material(ded_data, name,
        bar["e_mpa"], nu, bar["rho_kn_m3"], bar["fy_mpa"])

    # estimate j
    mat_ix_m4 = bar["ix_m4"]
    mat_iy_m4 = bar["iy_m4"]
    j = j_factor * (mat_ix_m4 + mat_iy_m4)

    # add section
    sec_id = add_section(ded_data, name, bar["a_m2"], mat_ix_m4, mat_iy_m4, j)
    
    # assign material and section to members
    for member_id in member_ids:
        assign_material(ded_data, member_id, material_id=mat_id)
        assign_section(ded_data, member_id, section_id=sec_id)

    return mat_id, sec_id