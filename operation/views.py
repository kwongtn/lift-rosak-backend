import pendulum
from django.db.models import OuterRef, Q, QuerySet, Subquery
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from chartography import models as chartography_models
from common.utils import get_trends
from generic.schema.enums import DateGroupings
from operation import models as operation_models
from spotting import models as spotting_models


class LineVehiclesSpottingTrend(APIView):
    def get(self, request: Request | HttpRequest, line_id, start_date, end_date):
        vehicles = operation_models.Vehicle.objects.filter(lines=line_id).in_bulk()

        trends = get_trends(
            start=pendulum.parse(start_date),
            end=pendulum.parse(end_date),
            date_group=DateGroupings.WEEK,
            groupby_field="spotting_date",
            count_model=spotting_models.Event,
            filters=Q(vehicle__lines=line_id),
            add_zero=True,
            additional_groupby={
                "vehicle_id": [k for k in vehicles.keys()],
            },
        )

        results = [
            {
                "vehicle": vehicles[trend["vehicle_id"]].identification_no,
                "count": trend["count"],
                "dateKey": trend["date_key"],
            }
            for trend in trends
        ]

        return Response(
            sorted(results, key=lambda d: f'{d["vehicle"]}'),
            status=status.HTTP_200_OK,
        )


class LineVehiclesStatusTrendCount(APIView):
    def get(
        self, request: Request | HttpRequest, line_id, source_str, start_date, end_date
    ):
        line = get_object_or_404(operation_models.Line, id=line_id)
        source = get_object_or_404(chartography_models.Source, name__iexact=source_str)

        snapshots = chartography_models.Snapshot.objects.filter(
            source_id=source.id,
            date__gte=pendulum.parse(start_date),
            date__lte=pendulum.parse(end_date),
            id=OuterRef("snapshot_id"),
        )

        vehicle_status_count_history: QuerySet[
            chartography_models.LineVehicleStatusCountHistory
        ] = chartography_models.LineVehicleStatusCountHistory.objects.filter(
            Q(snapshot__in=Subquery(snapshots.values_list("id", flat=True)))
            & Q(
                Q(
                    line_id=line.id,
                )
                | Q(
                    custom_line__mapped_lines=line,
                )
            )
        ).select_related("snapshot")

        results = [
            {
                "status": vehicle_status_count.status,
                "count": vehicle_status_count.count,
                "date": vehicle_status_count.snapshot.date,
            }
            for vehicle_status_count in vehicle_status_count_history
        ]

        return Response(
            sorted(results, key=lambda d: f'{d["date"]}__{d["status"]}'),
            status=status.HTTP_200_OK,
        )


class VehicleSpottingTrend(APIView):
    def get(self, request: Request | HttpRequest, vehicle_id, start_date, end_date):
        vehicle = get_object_or_404(operation_models.Vehicle, id=vehicle_id)

        trends = get_trends(
            start=pendulum.parse(start_date),
            end=pendulum.parse(end_date),
            date_group=DateGroupings.DAY,
            groupby_field="spotting_date",
            count_model=spotting_models.Event,
            filters=Q(vehicle_id=vehicle_id),
            add_zero=True,
            additional_groupby={},
            free_range=False,
        )

        results = [
            {
                "vehicle": vehicle.identification_no,
                "count": trend["count"],
                "dateKey": trend["date_key"],
                "dayOfWeek": trend["day_of_week"],
                "weekOfYear": trend["week_of_year"],
                "isLastDayOfMonth": trend["is_last_day_of_month"],
                "isLastWeekOfMonth": trend["is_last_week_of_month"],
            }
            for trend in trends
        ]

        return Response(
            sorted(results, key=lambda d: f'{d["dateKey"]}'),
            status=status.HTTP_200_OK,
        )
