"""Real-schema tests for the per-line pulse fields on ``operation.Line``.

Executes ``{ lines { ...pulse fields... } }`` through the assembled schema and
asserts the resolved values, including the "No data" path
(``passengerStatus: null``) for a line with no recent status report.
"""

import copy

import pytest
import strawberry
from asgiref.sync import sync_to_async
from dotmap import DotMap

from common.models import User
from incident.enums import PassengerStatus
from incident.models import LineStatusReport, SocialMediaLink
from incident.schema.loaders import IncidentContextLoaders
from operation.enums import VehicleStatus
from operation.models import Line, Vehicle, VehicleLine, VehicleType
from operation.schema.loaders import OperationContextLoaders

_LINE_QUERY = """
query {
  lines {
    id
    inServiceVehicleCount
    totalVehicleCount
    vehicleStatusCounts {
      status
      count
    }
    passengerStatus
    passengerStatusMessage
    statusReportCount
    pulseLinks {
      id
      url
    }
  }
}
"""


def _build_schema():
    import django

    django.setup()
    from rosak.schema import Query

    return strawberry.Schema(query=Query)


def _context(user=None):
    return DotMap(
        {
            "loaders": {
                "operation": copy.deepcopy(OperationContextLoaders),
                "incident": copy.deepcopy(IncidentContextLoaders),
            },
            "request": None,
            "response": None,
            "user": user,
        }
    )


async def _execute(query: str, user=None):
    result = await _build_schema().execute(query, context_value=_context(user))
    assert result.errors is None, result.errors
    return result.data


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


async def _make_user(firebase_id: str) -> User:
    return await sync_to_async(User.objects.create)(firebase_id=firebase_id)


async def _make_link(user: User, url: str) -> SocialMediaLink:
    return await sync_to_async(SocialMediaLink.objects.create)(url=url, user=user)


async def _make_report(line: Line, user: User, status: str, link=None):
    return await sync_to_async(LineStatusReport.objects.create)(
        line=line, status=status, user=user, link=link
    )


def _line(data, line_id):
    return next(item for item in data["lines"] if item["id"] == str(line_id))


@pytest.mark.django_db
async def test_line_fields_report_vehicle_counts_and_no_data_pulse():
    vehicle_type = await _make_vehicle_type("SchemaType")
    line = await _make_line("SF1")
    for i, status in enumerate(
        [
            VehicleStatus.IN_SERVICE,
            VehicleStatus.IN_SERVICE,
            VehicleStatus.OUT_OF_SERVICE,
        ]
    ):
        vehicle = await _make_vehicle(vehicle_type, f"SF-{i}", status)
        await _assign(vehicle, line)

    data = await _execute(_LINE_QUERY)

    item = _line(data, line.id)
    assert item["inServiceVehicleCount"] == 2
    assert item["totalVehicleCount"] == 3
    assert item["vehicleStatusCounts"] == [
        {"status": "IN_SERVICE", "count": 2},
        {"status": "NOT_SPOTTED", "count": 0},
        {"status": "OUT_OF_SERVICE", "count": 1},
        {"status": "DECOMMISSIONED", "count": 0},
        {"status": "MARRIED", "count": 0},
        {"status": "TESTING", "count": 0},
        {"status": "UNKNOWN", "count": 0},
    ]
    assert item["passengerStatus"] is None
    assert item["passengerStatusMessage"] is None
    assert item["statusReportCount"] == 0
    assert item["pulseLinks"] == []


@pytest.mark.django_db
async def test_line_fields_expose_consolidated_pulse_with_links():
    user = await _make_user("line-fields-user")
    line = await _make_line("SF2")
    link = await _make_link(user, "https://example.com/line-pulse")
    await _make_report(line, user, PassengerStatus.CROWDED, link=link)

    data = await _execute(_LINE_QUERY)

    item = _line(data, line.id)
    assert item["passengerStatus"] == "CROWDED"
    assert item["statusReportCount"] == 1
    assert item["passengerStatusCount"] == 1
    assert item["statusWindowMinutes"] == 15
    assert item["passengerStatusMessage"] == (
        "According to 1 social media entry, this line is Crowded."
    )
    assert item["pulseLinks"] == [{"id": str(link.id), "url": link.url}]
