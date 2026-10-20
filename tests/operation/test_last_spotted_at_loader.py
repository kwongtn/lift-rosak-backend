"""DB-level test for ``batch_load_last_spotted_at_from_vehicle_id``.

``Event.spotting_date`` is date-only, so vehicles that share a "last spotting date"
need the event's creation time to be ordered within that day.
"""

from datetime import date, datetime

import pytest
from asgiref.sync import sync_to_async

from common.models import User
from operation.enums import VehicleStatus
from operation.models import Vehicle, VehicleType
from operation.schema.loaders import batch_load_last_spotted_at_from_vehicle_id
from spotting.enums import SpottingEventType, SpottingVehicleStatus
from spotting.models import Event


def _make_event(vehicle, reporter, spotting_date, created, status) -> Event:
    event = Event.objects.create(
        vehicle=vehicle,
        reporter=reporter,
        spotting_date=spotting_date,
        status=status,
        type=SpottingEventType.JUST_SPOTTING,
    )
    # `created` is auto_now_add; backdate it explicitly.
    Event.objects.filter(pk=event.pk).update(created=created)
    return event


def _utc(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour)


@pytest.mark.django_db
async def test_last_spotted_at_orders_vehicles_sharing_a_spotting_date():
    vehicle_type = await sync_to_async(VehicleType.objects.create)(display_name="T")
    reporter = await sync_to_async(User.objects.create)(firebase_id="last-spotted-at")
    earlier, later, backfilled, never = [
        await sync_to_async(Vehicle.objects.create)(
            identification_no=f"LSA-{i}",
            vehicle_type=vehicle_type,
            status=VehicleStatus.IN_SERVICE,
        )
        for i in range(4)
    ]
    seen = SpottingVehicleStatus.IN_SERVICE

    await sync_to_async(_make_event)(
        earlier, reporter, date(2026, 10, 18), _utc(18, 14), seen
    )
    await sync_to_async(_make_event)(
        later, reporter, date(2026, 10, 18), _utc(18, 15), seen
    )
    # Backfilled: logged after the others, but for an older day -> its newest
    # spotting_date wins over `created`, so it must report that event's `created`.
    await sync_to_async(_make_event)(
        backfilled, reporter, date(2026, 10, 17), _utc(19, 9), seen
    )
    # A newer event that is not a real sighting must not move `later` forward.
    await sync_to_async(_make_event)(
        later,
        reporter,
        date(2026, 10, 19),
        _utc(19, 10),
        SpottingVehicleStatus.NOT_SPOTTED,
    )

    result = await batch_load_last_spotted_at_from_vehicle_id(
        [earlier.id, later.id, backfilled.id, never.id]
    )

    assert result == [_utc(18, 14), _utc(18, 15), _utc(19, 9), None]
    assert result[0] < result[1]
