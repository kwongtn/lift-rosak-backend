import pendulum
from django.db.models import Q
from django.http import HttpRequest
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

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
