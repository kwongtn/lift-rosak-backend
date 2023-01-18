import pandas as pd

from jejak.models import (
    Accessibility,
    AccessibilityBusRange,
    Bus,
    BusProviderRange,
    BusStop,
    BusStopBusRange,
    Captain,
    CaptainBusRange,
    CaptainProviderRange,
    EngineStatus,
    EngineStatusBusRange,
    Provider,
    Route,
    Trip,
    TripRange,
    TripRev,
    TripRevBusRange,
)

from .import_range_utils import (
    multi_fk_row_import,
    single_fk_range_import,
    single_side_multi_fk_range_import,
)

INPUT_FILENAME = "./@utils/2022-05-28_dedup.json"

DT_TARGET = "dt_gps"
RANGE_TARGET = "trip_no"

print("⏩ Reading data...")
df = pd.read_json(
    INPUT_FILENAME,
    lines=True,
    dtype={
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
    },
).rename(
    columns={
        "bus_no": "bus",
        "trip_no": "trip",
        "trip_rev_kind": "trip_rev",
        "busstop_id": "bus_stop",
        "captain_id": "captain",
    }
)

for model in [Bus, Captain, TripRev, EngineStatus, Accessibility, Provider, BusStop]:
    print(f"⏩ Importing data for {model.__name__.lower()}...")
    model_name = model.__name__.lower()
    identifiers = list(df[model_name].dropna().unique())

    model.objects.bulk_create(
        [model(identifier=identifier) for identifier in identifiers],
        ignore_conflicts=True,
    )

for (range_model, left_model, right_model) in [
    (BusProviderRange, Bus, Provider),
    (AccessibilityBusRange, Bus, Accessibility),
    (EngineStatusBusRange, Bus, EngineStatus),
    (TripRevBusRange, Bus, TripRev),
    # (BusRouteRange, Bus, Route),
    (BusStopBusRange, Bus, BusStop),
    (CaptainProviderRange, Captain, Provider),
    (CaptainBusRange, Captain, Bus),
]:
    print(
        f"⏩ Importing ranges for [{left_model.__name__.lower()}, {right_model.__name__.lower()}]..."
    )
    single_fk_range_import(
        df=df,
        range_model=range_model,
        left_model=left_model,
        right_model=right_model,
    )

# Trip No

multi_fk_row_import(
    df=df,
    groupings={
        "provider": Provider,
        "bus": Bus,
    },
    target_str="trip",
    target_model=Trip,
)
multi_fk_row_import(
    df=df,
    groupings={
        "provider": Provider,
    },
    target_str="route",
    target_model=Route,
)


single_side_multi_fk_range_import(
    df=df,
    range_model=TripRange,
    side_model=Trip,
    groupings={
        "provider": Provider,
        "bus": Bus,
    },
)
