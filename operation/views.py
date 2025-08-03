import pendulum
import polars as pl
from django.db.models import OuterRef, Q, QuerySet, Subquery
from django.http import HttpRequest, HttpResponse
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
    def get(
        self,
        request: Request | HttpRequest,
        line_id,
        start_date,
        end_date,
        **kwargs,
    ):
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

        csv_data = pl.DataFrame(results).sort("vehicle", "dateKey").write_csv(file=None)
        return HttpResponse(
            csv_data,
            content_type="text/csv",
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
            sorted(results, key=lambda d: f"{d['date']}__{d['status']}"),
            status=status.HTTP_200_OK,
        )


class VehicleSpottingTrend(APIView):
    def get(self, request: Request | HttpRequest, vehicle_id, start_date, end_date):
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
                "count": trend["count"],
                "dateKey": trend["date_key"],
                "dayOfWeek": trend["day_of_week"],
                "yearWeek": trend["year_week"],
                "isLastDayOfMonth": trend["is_last_day_of_month"],
                "isLastWeekOfMonth": trend["is_last_week_of_month"],
            }
            for trend in trends
        ]

        date_week_index_set = set()
        for result in results:
            year, month, day = result["dateKey"].split("-")
            result_date = pendulum.datetime(
                year=int(year), month=int(month), day=int(day)
            )

            date_week_index_set.add(
                (result_date.isocalendar().year, result_date.isocalendar().week)
            )

        date_week_index_dict = {}
        week_index = 0
        for year, week in sorted(
            list(date_week_index_set), key=lambda i: f"{i[0]}W{i[1]}"
        ):
            date_week_index_dict[f"{year}W{week}"] = week_index
            week_index += 1

        return Response(
            {
                "data": results,
                "mappings": {
                    "yearWeek": date_week_index_dict,
                },
            },
            status=status.HTTP_200_OK,
        )
