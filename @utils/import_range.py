import pandas as pd
from django.db.models import Q
from psycopg2.extras import DateTimeTZRange

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
    aggregate_start_end_dt,
    group_is_close_dt,
    multi_fk_row_import,
    single_fk_range_import,
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


groupings = {
    "provider": Provider,
    "bus": Bus,
}

# Sort then assign groupings based on change of value
print("⏩ Sorting values...")
grouped = df.sort_values([*groupings.keys(), DT_TARGET])

df_groupings = grouped[RANGE_TARGET].astype(str)

for key in groupings.keys():
    df_groupings = grouped[key].astype(str) + df_groupings

grouped["group"] = df_groupings.ne(df_groupings.shift()).cumsum()

# Separate data based on group
print("⏩ Splitting data into dataframes...")
dfs = [data for name, data in grouped.groupby("group")]

# Generate start_dt and end_dt of each group
print("⏩ Aggregrating values...")
ranges = aggregate_start_end_dt(
    dfs=dfs,
    target_key=RANGE_TARGET,
    grouping_keys=groupings.keys(),
)


print("⏩ Regrouping values...")
for key in ranges:
    if len(ranges[key]) > 1:
        while group_is_close_dt(ranges[key]):
            pass

# Prepare data for addition
bus_set = set()
range_target_set = set()
provider_set = set()

for (range_target, provider, bus) in ranges.keys():
    range_target_set.add((range_target, provider, bus))
    provider_set.add(provider)
    bus_set.add(bus)

print("⏩ Obtaining preliminary values...")

buses = Bus.objects.filter(identifier__in=bus_set).in_bulk(field_name="identifier")
providers = Provider.objects.filter(identifier__in=provider_set).in_bulk(
    field_name="identifier"
)

Trip.objects.bulk_create(
    [
        Trip(
            identifier=range_target,
            bus_id=buses[bus].id,
            provider_id=providers[provider].id,
        )
        for (range_target, provider, bus) in range_target_set
    ],
    ignore_conflicts=True,
)

criteria = Q()
# It is guaranteed that range_target_set is not empty
for (range_target, provider, bus) in range_target_set:
    criteria |= Q(
        provider_id=providers[provider].id,
        bus_id=buses[bus].id,
        identifier=range_target,
    )

trips = Trip.objects.filter(criteria).select_related(*groupings.keys())
trips_dict = {}
for trip in trips:
    trips_dict[trip.provider.identifier, trip.bus.identifier, trip.identifier] = trip

print("⏩ Inserting other values...")
to_create = []
for key in ranges:
    for elem in ranges[key]:
        to_create.append(
            TripRange(
                trip=trips_dict[key],
                dt_range=DateTimeTZRange(
                    lower=elem["start_dt"],
                    upper=elem["end_dt"],
                    bounds="[]",
                ),
            )
        )

TripRange.objects.bulk_create(to_create, ignore_conflicts=True)
