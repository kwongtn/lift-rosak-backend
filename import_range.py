import os

import django
import pandas as pd
from django.contrib.gis.geos import Point
from django.db import transaction

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rosak.settings")
django.setup()

from jejak.models import (  # noqa E402
    Accessibility,
    AccessibilityBusRange,
    Bus,
    BusProviderRange,
    BusRouteRange,
    BusStop,
    BusStopBusRange,
    Captain,
    CaptainBusRange,
    CaptainProviderRange,
    EngineStatus,
    EngineStatusBusRange,
    Location,
    Provider,
    Route,
    Trip,
    TripRange,
    TripRev,
    TripRevBusRange,
)
from utils.import_range_utils import (  # noqa E402
    multi_fk_range_import,
    multi_fk_row_import,
    single_fk_range_import,
    single_side_multi_fk_range_import,
)

INPUT_FILENAME = "./utils/2022-05_0.json"

DT_TARGET = "dt_received"

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
        "trip_rev_kind": "triprev",
        "busstop_id": "busstop",
        "captain_id": "captain",
        "engine_status": "enginestatus",
    }
)

# df['dir'] = (df['dir'] == 1990).astype(str)

expected_cols = [
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

print("Df columns: ", df.columns.tolist())
print("Expected columns: ", expected_cols)

assert df.columns.tolist() == expected_cols

# for model in [Bus, Captain, TripRev, EngineStatus, Accessibility, Provider, BusStop]:
#     print(f"⏩ Importing data for {model.__name__.lower()}...")
#     model_name = model.__name__.lower()
#     identifiers = list(df[model_name].dropna().unique())

#     model.objects.abulk_create(
#         [model(identifier=identifier) for identifier in identifiers],
#         ignore_conflicts=True,
#     )

# for (range_model, left_model, right_model) in [
#     (BusProviderRange, Bus, Provider),
#     (AccessibilityBusRange, Bus, Accessibility),
#     (EngineStatusBusRange, Bus, EngineStatus),
#     (TripRevBusRange, Bus, TripRev),
#     (BusStopBusRange, Bus, BusStop),
#     (CaptainProviderRange, Captain, Provider),
#     (CaptainBusRange, Captain, Bus),
# ]:
#     print(
#         f"⏩ Importing ranges for [{left_model.__name__.lower()}, {right_model.__name__.lower()}]..."
#     )
#     single_fk_range_import(
#         df=df,
#         range_model=range_model,
#         left_model=left_model,
#         right_model=right_model,
#     )

# multi_fk_row_import(
#     df=df,
#     groupings={
#         "provider": Provider,
#         "bus": Bus,
#     },
#     target_str="trip",
#     target_model=Trip,
# )
# multi_fk_row_import(
#     df=df,
#     groupings={
#         "provider": Provider,
#     },
#     target_str="route",
#     target_model=Route,
# )


# single_side_multi_fk_range_import(
#     df=df,
#     range_model=TripRange,
#     side_model=Trip,
#     groupings={
#         "provider": Provider,
#         "bus": Bus,
#     },
# )

# multi_fk_range_import(
#     df=df,
#     range_model=BusRouteRange,
#     left_model=Bus,
#     right_model=Route,
#     left_groupings=[],
#     right_groupings=[Provider],
# )

# Import location data
identifiers = list(df["bus"].dropna().unique())
bus_dict = Bus.objects.filter(identifier__in=identifiers).in_bulk(
    field_name="identifier"
)

with transaction.atomic():
    location_datas = []
    for i, row in df.iterrows():
        location_datas.append(
            Location(
                dt_received=row["dt_received"],
                dt_gps=row["dt_gps"],
                location=Point(
                    x=row["longitude"],
                    y=row["latitude"],
                ),
                dir=row["dir"] if str(row["dir"]) != "<NA>" else None,
                speed=row["speed"],
                angle=row["angle"],
                bus_id=bus_dict[row["bus"]].id,
            )
        )

        if len(location_datas) % 10000 == 0:
            Location.objects.bulk_create(
                location_datas,
                batch_size=1000,
                ignore_conflicts=True,
            )
            location_datas = []
