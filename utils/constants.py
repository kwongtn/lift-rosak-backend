from datetime import timedelta

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

DT_TARGET = "dt_received"


GROUP_THRESHOLDS = {
    "AccessibilityBusRange": timedelta(hours=1),
    "BusProviderRange": timedelta(hours=1),
    "BusRouteRange": timedelta(minutes=5),
    "BusStopBusRange": timedelta(minutes=3),
    "CaptainBusRange": timedelta(minutes=5),
    "CaptainProviderRange": timedelta(hours=1),
    "EngineStatusBusRange": timedelta(minutes=3),
    "TripRange": timedelta(minutes=3),
    "TripRevBusRange": timedelta(minutes=3),
}

DE_RANGE_THRESHOLDS = {
    "AccessibilityBusRange": timedelta(days=30),
    "BusProviderRange": timedelta(days=30),
    "BusRouteRange": timedelta(days=1),
    "BusStopBusRange": timedelta(hours=1),
    "CaptainBusRange": timedelta(days=1),
    "CaptainProviderRange": timedelta(days=30),
    "EngineStatusBusRange": timedelta(days=30),
    "TripRange": timedelta(days=1),
    "TripRevBusRange": timedelta(days=1),
}

RANGE_WARN_THRESHOLDS = {
    "AccessibilityBusRange": timedelta(days=365),
    "BusProviderRange": timedelta(days=365),
    "BusRouteRange": timedelta(days=1),
    "BusStopBusRange": timedelta(hours=1),
    "CaptainBusRange": timedelta(days=1),
    "CaptainProviderRange": timedelta(days=30),
    "EngineStatusBusRange": timedelta(days=30),
    "TripRange": timedelta(days=1),
    "TripRevBusRange": timedelta(days=1),
}
