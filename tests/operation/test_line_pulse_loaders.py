"""DB-level tests for the per-line operation DataLoaders.

Covers ``batch_load_line_vehicle_counts`` (one aggregate for N lines) and
``batch_load_line_pulse`` (thin ordered wrapper over the incident service).
"""

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from django.db import connection
from django.test.utils import CaptureQueriesContext

from common.models import User
from incident.enums import PassengerStatus
from incident.models import LineStatusReport
from operation.enums import VehicleStatus
from operation.models import Line, Vehicle, VehicleLine, VehicleType
from operation.schema.loaders import (
    batch_load_line_pulse,
    batch_load_line_vehicle_counts,
)


async def _make_line(code: str) -> Line:
    return await sync_to_async(Line.objects.create)(
        code=code,
        display_name=f"Line {code}",
        display_color="#FF0000",
    )


async def _make_vehicle_type(name: str) -> VehicleType:
    return await sync_to_async(VehicleType.objects.create)(display_name=name)


async def _make_vehicle(
    vehicle_type: VehicleType, identification_no: str, status: str
) -> Vehicle:
    return await sync_to_async(Vehicle.objects.create)(
        identification_no=identification_no,
        vehicle_type=vehicle_type,
        status=status,
    )


async def _assign(vehicle: Vehicle, line: Line) -> VehicleLine:
    return await sync_to_async(VehicleLine.objects.create)(vehicle=vehicle, line=line)


async def _make_user(n: int) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=f"line-loader-{n}")


async def _make_report(line: Line, user: User, status: str) -> LineStatusReport:
    return await sync_to_async(LineStatusReport.objects.create)(
        line=line, status=status, user=user
    )


def _counts(in_service: int, total: int, **statuses: int) -> dict:
    """Loader result shape: totals plus a zero-filled per-status breakdown."""
    breakdown = {status.value: 0 for status in VehicleStatus}
    breakdown.update(statuses)
    return {"in_service": in_service, "total": total, "status_counts": breakdown}


@pytest.mark.django_db
async def test_vehicle_counts_split_in_service_from_total():
    vehicle_type = await _make_vehicle_type("CountType")
    line = await _make_line("VC1")
    for i, status in enumerate(
        [
            VehicleStatus.IN_SERVICE,
            VehicleStatus.IN_SERVICE,
            VehicleStatus.OUT_OF_SERVICE,
        ]
    ):
        vehicle = await _make_vehicle(vehicle_type, f"VC-{i}", status)
        await _assign(vehicle, line)

    counts = await batch_load_line_vehicle_counts([line.id])

    assert counts == [
        _counts(
            2,
            3,
            IN_SERVICE=2,
            OUT_OF_SERVICE=1,
        )
    ]
    # Every enum member is present so the UI chart always has a full series.
    assert set(counts[0]["status_counts"]) == {s.value for s in VehicleStatus}


@pytest.mark.django_db
async def test_vehicle_counts_zero_for_line_without_vehicles():
    line = await _make_line("VC2")

    counts = await batch_load_line_vehicle_counts([line.id])

    assert counts == [_counts(0, 0)]


@pytest.mark.django_db
async def test_vehicle_counts_returned_in_key_order():
    vehicle_type = await _make_vehicle_type("OrderType")
    populated = await _make_line("VC3")
    empty = await _make_line("VC4")
    vehicle = await _make_vehicle(vehicle_type, "VC-ORDER", VehicleStatus.IN_SERVICE)
    await _assign(vehicle, populated)

    counts = await batch_load_line_vehicle_counts([empty.id, populated.id])

    assert counts == [
        _counts(0, 0),
        _counts(1, 1, IN_SERVICE=1),
    ]


@pytest.mark.django_db
async def test_vehicle_counts_unknown_key_is_zero():
    line = await _make_line("VC5")

    counts = await batch_load_line_vehicle_counts([line.id, 999999999])

    assert counts == [
        _counts(0, 0),
        _counts(0, 0),
    ]


@pytest.mark.django_db
def test_vehicle_counts_batch_into_one_query_for_many_lines():
    vehicle_type = VehicleType.objects.create(display_name="BatchType")
    lines = []
    for i in range(5):
        line = Line.objects.create(
            code=f"VCB{i}",
            display_name=f"Line VCB{i}",
            display_color="#FF0000",
        )
        vehicle = Vehicle.objects.create(
            identification_no=f"VCB-{i}",
            vehicle_type=vehicle_type,
            status=VehicleStatus.IN_SERVICE,
        )
        VehicleLine.objects.create(vehicle=vehicle, line=line)
        lines.append(line)

    ids = [line.id for line in lines]
    with CaptureQueriesContext(connection) as captured:
        counts = async_to_sync(batch_load_line_vehicle_counts)(ids)

    assert len(captured.captured_queries) == 1
    assert counts == [_counts(1, 1, IN_SERVICE=1) for _ in lines]


@pytest.mark.django_db
async def test_line_pulse_loader_orders_by_keys_and_falls_back_empty():
    user = await _make_user(1)
    with_report = await _make_line("LP1")
    empty = await _make_line("LP2")
    await _make_report(with_report, user, PassengerStatus.CROWDED)

    pulses = await batch_load_line_pulse([empty.id, with_report.id])

    assert pulses[0].status is None
    assert pulses[0].message is None
    assert pulses[0].count == 0
    assert pulses[0].links == []
    assert pulses[1].status == PassengerStatus.CROWDED
    assert pulses[1].count == 1


@pytest.mark.django_db
async def test_line_pulse_loader_unknown_key_returns_empty_pulse():
    pulses = await batch_load_line_pulse([999999999])

    assert len(pulses) == 1
    assert pulses[0].status is None
    assert pulses[0].count == 0
