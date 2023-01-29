DTYPE = {
    "latitude": "Float64",
    "longitude": "Float64",
    "dir": "Float32",
    "speed": "Float32",
    "angle": "Float32",
    "captain_id": "Int32",
    "trip_rev_kind": "Int32",
    "engine_status": "Int32",
    "accessibility": "Int32",
    "busstop_id": "Int32",
}

COL_RENAME = {
    "bus_no": "bus",
    "trip_no": "trip",
    "trip_rev_kind": "triprev",
    "busstop_id": "busstop",
    "captain_id": "captain",
    "engine_status": "enginestatus",
}

EXPECTED_COLS = set(
    [
        "dt_received",
        "dt_gps",
        "latitude",
        "longitude",
        "dir",
        "speed",
        "angle",
        "route",
        "bus",
        "trip",
        "captain",
        "triprev",
        "enginestatus",
        "accessibility",
        "provider",
        "busstop",
    ]
)
