import json
from beartype import beartype

def read_ded(filepath: str) -> dict:
    """
    ded_data is a nested dict:

    'version'   : (str) "2.0"
    'name'     : (str) "filename"
    'timestamp': (str) "yyyy-mm-ddThh:mm:ss:{dec}Z"
    'snapshot' : dict("name": (str) "filename", 
                      "nodes": list
                      "materials": list
                      "sections": list
                      "elements": list
                      "supports": list
                      "loads": list
                      "loadCases": list
                      "combinations": list
                      "plates": list
                      "quads": list
                      "constraints": list
                      "connectors": list
                      "nextId": dict
                      'localAxisConvention': str
                      'codeSettings': dict
                      'detailing': dict
                      'exports': list
                      'manualEdits': list
                      'footings': list
                      'geotechnical': dict
                      'footingMatPreferences': dict
    'appMode'               : (str)  "basico"
    'analysisMode'          : (str)  "3d"
    'axisConvention3D'      : (str)  "rightHand"
    'viewportPresentation3D': (str)  "native3d"
    'includeSelfWeight'     : (bool) true

    "nodes": list(
                    list(int,
                        dict('id',
                            'id': (int)    1
                            'x' : (float)  0.0           # m
                            'y' : (float)  0.0           # m
                            'z' : (float)  6.096         # m
                            )
                        )
                    )

    "materials": list(
                    list(int, 
                        dict('id',
                            'name'   : (str)           "6063-T6" 
                            'e'      : (float)         70000         # MPa
                            'nu'     : (float)         0.3
                            'rho'    : (float)         27            # kN/m^3
                            'fy'     : (float)         170           # Mpa
                            'gradeId': (optional, str) "alu-6063-t6"
                            )
                        )
                    )
    
    "sections": list(
                    list(int,
                        dict('id',
                            'name' : (str)            "Body Tube"
                            'a'    : (float)          0.00104758     # m^2, cross-section area
                            'iz'   : (float)          3.1265e-06     # m^4, moment of inertia about z
                            'iy'   : (float)          3.1265e-06     # m^4, moment of inertia about y
                            'j'    : (optional, float) 6.2530e-06    # m^4, polar moment of inertia
                            'b'    : (optional, float) 0.156718      # m, width / outer diameter
                            'h'    : (optional, float) 0.156718      # m, height / outer diameter
                            'shape': (optional, str)   "CHS"         # e.g. circular hollow section
                            't'    : (optional, float) 0.002159      # m, wall thickness
                            )
                        )
                    )

    "elements": list(                                         # members
                    list(int,
                        dict('id',
                            'id'        : (int)   7
                            'type'      : (str)   "frame"
                            'nodeI'     : (int)   3            # id of start node
                            'nodeJ'     : (int)   8            # id of end node
                            'materialId': (int)   1            # id of entry in "materials"
                            'sectionId' : (int)   3            # id of entry in "sections"
                            'releaseI'  : dict('my': (bool), 'mz': (bool), 't': (bool))   # end-I releases
                            'releaseJ'  : dict('my': (bool), 'mz': (bool), 't': (bool))   # end-J releases
                            )
                        )
                    )

    "supports": list(
                    list(int,
                        dict('id',
                            'id'          : (int)   1
                            'nodeId'      : (int)   3
                            'type'        : (str)   "custom3d"
                            'dofRestraints': dict(
                                'tx': (bool)         # True = restrained, False = free
                                'ty': (bool)
                                'tz': (bool)
                                'rx': (bool)
                                'ry': (bool)
                                'rz': (bool)
                                )
                            'dofFrame'    : (str)   "global"   # axes the restraints are expressed in
                            )
                        )
                    )

    "loads": list(
                dict('type'  : (str)  "nodal3d",
                     'data'  : dict(
                         'id'    : (int)    5
                         'nodeId': (int)    12
                         'fx'    : (float)  0.0          # kN
                         'fy'    : (float)  0.0          # kN
                         'fz'    : (float)  6.67233242   # kN
                         'mx'    : (float)  0.0          # kN*m
                         'my'    : (float)  0.0          # kN*m
                         'mz'    : (float)  0.0          # kN*m
                         'caseId': (int)    2            # id of entry in "loadCases"
                         )
                    )
                )

    "loadCases": list(
                    dict('type': (str)  "D"      # D=Dead, L=Live, W=Wind, E=Earthquake
                         'id'  : (int)  1
                         'name': (str)  "Dead Load"
                        )
                    )

    "combinations": list(
                        dict('id'     : (int)  1
                             'name'   : (str)  "1.2D + 1.6L"
                             'factors': list(
                                 dict('caseId': (int)    1       # id of entry in "loadCases"
                                      'factor': (float)  1.2
                                     )
                                 )
                            )
                        )
    
    "nextId": dict(
                'node'        : (int)  24      # next unused id for "nodes"
                'material'    : (int)  6       # next unused id for "materials"
                'section'     : (int)  6       # next unused id for "sections"
                'element'     : (int)  29      # next unused id for "elements"
                'support'     : (int)  5       # next unused id for "supports"
                'load'        : (int)  11      # next unused id for "loads"
                'loadCase'    : (int)  6       # next unused id for "loadCases"
                'combination' : (int)  5       # next unused id for "combinations"
                'plate'       : (int)  1       # next unused id for plates
                'quad'        : (int)  1       # next unused id for quads
                'group'       : (int)  1       # next unused id for groups
                'connector'   : (int)  1       # next unused id for connectors
                'footing'     : (int)  1       # next unused id for footings
                'soilProfile' : (int)  1       # next unused id for soil profiles
                )
    """
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
