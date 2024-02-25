from datetime import timedelta

import polars as pl

DTYPE = {
    "latitude": "Float64",
    "longitude": "Float64",
    "dir": "Float32",
    "speed": "Float32",
    "angle": "Float32",
    "captain_id": "String",
    "trip_rev_kind": "String",
    "engine_status": "String",
    "accessibility": "String",
    "busstop_id": "String",
}

PL_DTYPE = {
    "dt_received": pl.String(),
    "dt_gps": pl.String(),
    "latitude": pl.Float64(),
    "longitude": pl.Float64(),
    "dir": pl.Float32(),
    "speed": pl.Float32(),
    "angle": pl.Float32(),
    "route": pl.String(),
    "bus_no": pl.String(),
    "trip_no": pl.String(),
    "captain_id": pl.String(),
    "trip_rev_kind": pl.String(),
    "engine_status": pl.Int32(),
    "accessibility": pl.Int32(),
    "busstop_id": pl.String(),
    "provider": pl.String(),
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
