from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from django.db.models import Q
from psycopg2.extras import DateTimeTZRange

from jejak.models import Bus, Provider, Trip, TripRange

INPUT_FILENAME = "./@utils/2022-05-28_dedup.json"

DT_TARGET = "dt_gps"
RANGE_TARGET = "trip_no"

print("⏩ Reading data...")
df = pd.read_json(INPUT_FILENAME, lines=True)


# Trip No

groupings = {
    "provider": Provider,
    "bus_no": Bus,
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
dfs = []
for name, data in grouped.groupby("group"):
    dfs.append(data)

# Generate start_dt and end_dt of each group
print("⏩ Aggregrating values...")
ranges = defaultdict(list)
for elem in dfs:
    operation_dict = {
        RANGE_TARGET: elem.loc[:, RANGE_TARGET].iloc[0],
    }

    for key in groupings.keys():
        operation_dict[key] = elem.loc[:, key].iloc[0]

    if operation_dict[RANGE_TARGET] is not None:
        ranges[tuple([operation_dict[key] for key in operation_dict.keys()])].append(
            {
                "start_dt": elem.aggregate(np.min)[DT_TARGET],
                "end_dt": elem.aggregate(np.max)[DT_TARGET],
            }
        )


# If this end_dt and next start_dt is less than 5 minutes,
# group them together.
def group_close_dt(range_group):
    for index in range(0, len(range_group) - 1):
        if datetime.fromisoformat(
            range_group[index + 1]["start_dt"]
        ) - datetime.fromisoformat(range_group[index]["end_dt"]) < timedelta(minutes=5):
            range_group[index]["end_dt"] = range_group[index + 1]["end_dt"]
            del range_group[index + 1]
            return True

    return False


print("⏩ Regrouping values...")
for key in ranges:
    counter = 0
    if len(ranges[key]) > 1:
        while group_close_dt(ranges[key]):
            counter += 1
            # print(key, counter)
            # print(ranges[key])

# Prepare data for addition
bus_no_set = set()
range_target_set = set()
provider_set = set()

for (range_target, provider, bus_no) in ranges.keys():
    provider_set.add(provider)
    bus_no_set.add(bus_no)
    range_target_set.add((provider, bus_no, range_target))

print("⏩ Inserting preliminary values...")

Bus.objects.bulk_create(
    [Bus(identifier=bus_no) for bus_no in bus_no_set],
    ignore_conflicts=True,
)
buses = Bus.objects.filter(identifier__in=bus_no_set).in_bulk(field_name="identifier")

Provider.objects.bulk_create(
    [Provider(identifier=provider) for provider in provider_set],
    ignore_conflicts=True,
)
providers = Provider.objects.filter(identifier__in=provider_set).in_bulk(
    field_name="identifier"
)

Trip.objects.bulk_create(
    [
        Trip(
            identifier=range_target,
            bus_id=buses[bus_no].id,
            provider_id=providers[provider].id,
        )
        for (provider, bus_no, range_target) in range_target_set
    ],
    ignore_conflicts=True,
)

criteria = Q()
# It is guaranteed that range_target_set is not empty
for (provider, bus_no, range_target) in range_target_set:
    criteria |= Q(
        provider_id=providers[provider].id,
        bus_id=buses[bus_no].id,
        identifier=range_target,
    )

trips = Trip.objects.filter(criteria).select_related("provider", "bus")
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
