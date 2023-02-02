import argparse
import os

import django
import pandas as pd

from utils.constants import COL_RENAME, DTYPE, EXPECTED_COLS
from utils.db import wrap_errors

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

argParser = argparse.ArgumentParser()
argParser.add_argument("-f", "--file", help="Input filename.")

args = argParser.parse_args()
# INPUT_FILENAME = "./utils/2022-05_0.json"
INPUT_FILENAME: str = args.file
FILENAME = INPUT_FILENAME.split("/")[-1]

sleep_time = 5
DT_TARGET = "dt_gps"

print(f"{FILENAME} ⏩ Reading data...")
df = pd.read_json(
    INPUT_FILENAME,
    lines=True,
    dtype=DTYPE,
).rename(columns=COL_RENAME)

print(
    f"{FILENAME} Not-expected columns: ",
    EXPECTED_COLS.difference(set(df.columns.tolist())),
)
assert set(df.columns.tolist()) == EXPECTED_COLS

for model in [Bus, Captain, TripRev, EngineStatus, Accessibility, Provider, BusStop]:
    model_name = model.__name__.lower()
    identifiers = list(df[model_name].dropna().unique())

    print(f"⏩ Importing data for {model.__name__.lower()}...")
    wrap_errors(
        fn=model.objects.bulk_create,
        objs=[model(identifier=identifier) for identifier in identifiers],
        ignore_conflicts=True,
    )

for (range_model, left_model, right_model) in [
    (BusProviderRange, Bus, Provider),
    (AccessibilityBusRange, Bus, Accessibility),
    (EngineStatusBusRange, Bus, EngineStatus),
    (TripRevBusRange, Bus, TripRev),
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

multi_fk_row_import(
    df=df,
    groupings={
        "provider": Provider,
        "bus": Bus,
    },
    target_model=Trip,
)
multi_fk_row_import(
    df=df,
    groupings={
        "provider": Provider,
    },
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

multi_fk_range_import(
    df=df,
    range_model=BusRouteRange,
    left_model=Bus,
    right_model=Route,
    left_groupings=[],
    right_groupings=[Provider],
)
