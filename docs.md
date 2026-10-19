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
                )
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
