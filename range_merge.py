import os
from collections import defaultdict

import django
from django.db.models import Q
from psycopg2.extras import DateTimeTZRange

from utils.constants import GROUP_THRESHOLDS
from utils.db import wrap_errors

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rosak.settings")
django.setup()

from jejak.models import (  # noqa E402
    AccessibilityBusRange,
    BusProviderRange,
    BusRouteRange,
    BusStopBusRange,
    CaptainBusRange,
    CaptainProviderRange,
    EngineStatusBusRange,
    TripRange,
    TripRevBusRange,
)

batch_size = 1000

for (model, distinct_on) in [
    (BusProviderRange, ("bus_id", "provider_id")),
    (AccessibilityBusRange, ("bus_id", "accessibility_id")),
    (EngineStatusBusRange, ("bus_id", "engine_status_id")),
    (TripRevBusRange, ("bus_id", "trip_rev_id")),
    (BusStopBusRange, ("bus_id", "bus_stop_id")),
    (CaptainProviderRange, ("captain_id", "provider_id")),
    (CaptainBusRange, ("bus_id", "captain_id")),
    (TripRange, ("trip_id",)),
    (BusRouteRange, ("bus_id", "route_id")),
]:
    model_key = model.__name__
    print(f"⏩ [{model_key}] Deduplicating ranges...")

    print(f"⏩ [{model_key}] Requesting unique values...")
    distincts = wrap_errors(model.objects.distinct, *distinct_on)

    uniques = set()
    for elem in distincts:
        to_add = ()
        for key in distinct_on:
            to_add += (getattr(elem, key),)

        uniques.add(tuple(to_add))

    to_delete = set()
    update_count = 0
    current_count = 0
    while uniques:
        to_update_ids = set()
        to_update = []
        debug_suffix: str = f"({current_count:,} / {len(distincts):,})"

        curr_iterator: list[tuple] = []
        while len(curr_iterator) < batch_size and uniques:
            curr_iterator.append(uniques.pop())

        current_count += len(curr_iterator)
        print(f"⏩ [{model_key}] Generating unique key query... {debug_suffix}")
        query = Q()
        for ids in curr_iterator:
            sub_query = Q()
            for key in distinct_on:
                sub_query &= Q(**{key: ids[len(sub_query)]})

            assert len(sub_query) > 0

            query |= sub_query

        assert len(query) > 0

        print(f"⏩ [{model_key}] Generating dedup key tuple... {debug_suffix}")
        objs = defaultdict(list)
        for obj in model.objects.filter(query).order_by("dt_range"):
            objs[tuple([getattr(obj, key) for key in distinct_on])].append(obj)

        print(f"⏩ [{model_key}] Deduplicating... {debug_suffix}")
        for range_list in objs.values():
            if len(range_list) == 1:
                continue

            prev = None

            for curr in range_list:
                if prev is not None and (
                    curr.dt_range.lower < prev.dt_range.upper
                    or curr.dt_range.lower - prev.dt_range.upper
                    < GROUP_THRESHOLDS[model_key]
                ):
                    if curr.dt_range.upper > prev.dt_range.upper:
                        prev.dt_range = DateTimeTZRange(
                            lower=prev.dt_range.lower,
                            upper=curr.dt_range.upper,
                            bounds="[]",
                        )
                        if prev.id not in to_update_ids:
                            to_update.append(prev)
                            to_update_ids.add(prev.id)

                    to_delete.add(curr.id)

                else:
                    prev = curr

            wrap_errors(model.objects.bulk_update, to_update, ["dt_range"])

            print(f"📜 [{model_key}] Updated {len(to_update):,} {model_key}s")

        print(f"✅ [{model_key}] Done deduplication... {debug_suffix}")

    print(f"📜 [{model_key}] Updated in total {len(to_update):,} {model_key}s")

    print(f"📜 [{model_key}] Deleting {len(to_delete):,} {model_key}s")
    model.objects.filter(id__in=to_delete).delete()

    print(f"✅ [{model_key}] Done.")
