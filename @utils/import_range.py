from typing import Union

import pandas as pd
from django.db.models import Q
from psycopg2.extras import DateTimeTZRange

from jejak.models import (
    Accessibility,
    Bus,
    BusProviderRange,
    BusStop,
    Captain,
    EngineStatus,
    Provider,
    Route,
    Trip,
    TripRange,
    TripRev,
)

from .import_range_utils import (
    aggregate_start_end_dt,
    group_is_close_dt,
    identifier_detail_abstract_model_input,
    single_fk_range_import,
)

INPUT_FILENAME = "./@utils/2022-05-28_dedup.json"

DT_TARGET = "dt_gps"
RANGE_TARGET = "trip_no"

print("⏩ Reading data...")
str_none_type = Union[str, None]
df = pd.read_json(
    INPUT_FILENAME,
    lines=True,
    dtype={
        "route": str_none_type,
        "bus_no": str_none_type,
        "captain_id": str_none_type,
        "trip_rev_kind": str_none_type,
        "engine_status": str_none_type,
        "accessibility": str_none_type,
        "busstop_id": str_none_type,
    },
).rename(columns={"bus_no": "bus"})


identifier_detail_abstract_model_input(
    model=Route,
    identifiers=list(df["route"].dropna().unique()),
)
identifier_detail_abstract_model_input(
    model=Bus,
    identifiers=list(df["bus"].unique()),
)
identifier_detail_abstract_model_input(
    model=Captain,
    identifiers=list(df["captain_id"].dropna().unique()),
)
identifier_detail_abstract_model_input(
    model=TripRev,
    identifiers=list(df["trip_rev_kind"].dropna().unique()),
)
identifier_detail_abstract_model_input(
    model=EngineStatus,
    identifiers=list(df["engine_status"].dropna().unique()),
)
identifier_detail_abstract_model_input(
    model=Accessibility,
    identifiers=list(df["accessibility"].dropna().unique()),
)
identifier_detail_abstract_model_input(
    model=Provider,
    identifiers=list(df["provider"].unique()),
)
identifier_detail_abstract_model_input(
    model=BusStop,
    identifiers=list(df["busstop_id"].dropna().unique()),
)

single_fk_range_import(
    df=df,
    range_model=BusProviderRange,
    left_model=Bus,
    right_model=Provider,
    left_key="bus",
    right_key="provider",
)

# Trip No

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
