import logging
from collections import defaultdict
from datetime import datetime, timedelta

import requests
from django.db.models import Count, Q
from django.utils.timezone import now

from chartography.enums import DataSources
from chartography.models import (
    LineVehicleStatusCountHistory,
    Snapshot,
    Source,
    SourceCustomLine,
)
from operation.enums import VehicleStatus
from operation.models import Line, VehicleLine
from rosak.celery import app as celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def aggregate_line_vehicle_status_mlptf_task(
    self,
    *args,
    triggered_by_id=None,
    force=False,
    **kwargs,
):
    source: Source = Source.objects.get(name=DataSources.MLPTF)

    # Get snapshot now, date would be previous day.
    # It is expected we do it at next day 5am.
    snapshot: Snapshot = Snapshot.objects.create(
        date=now() - timedelta(days=1),
        source_id=source.id,
        triggered_by_id=triggered_by_id,
    )

    query_dict = defaultdict()
    for line in Line.objects.all():
        for status in [i[0] for i in VehicleStatus.choices]:
            query_dict[f"{line.id}__{status}"] = Count(
                "id",
                filter=Q(
                    line_id=line.id,
                    vehicle__status=status,
                ),
            )

    stats = VehicleLine.objects.aggregate(**query_dict)

    create_objs = []
    for k, v in stats.items():
        line_id, status = k.split("__")

        create_objs.append(
            LineVehicleStatusCountHistory(
                snapshot_id=snapshot.id,
                line_id=line_id,
                status=status,
                count=v,
            )
        )

    LineVehicleStatusCountHistory.objects.bulk_create(
        create_objs,
        ignore_conflicts=True,
    )


@celery_app.task(bind=True)
def aggregate_line_vehicle_status_mtrec_task(self, *args, **kwargs):
    source: Source = Source.objects.get(name=DataSources.MTREC)

    res = requests.get(
        "https://spotters.mtrec.name.my/api/listall",
        headers={"referer": "https://spotters.mtrec.name.my/analytics-2.html"},
    ).json()

    timestamp = datetime.strptime(
        res.get("Last_Updated", None), "%d %B %Y, %I:%M:%S %p"
    )
    snapshot: Snapshot = Snapshot.objects.create(
        date=timestamp - timedelta(days=1),
        source_id=source.id,
    )

    short_code_line_ids_map = {
        "KGL": [2],
        "PYL": [3],
        "AGSPL": [5, 9],
        "MRL": [1],
        "KJL": [4],
        "ERL": [8],
        "ETS": [10],
        "Komuter": [13, 14],
        "DMU": [],
        "Locomotive": [],
    }

    key_status_map = {
        "Decommissioned": VehicleStatus.DECOMMISSIONED,
        "In_Service": VehicleStatus.IN_SERVICE,
        "Not_Spotted": VehicleStatus.NOT_SPOTTED,
    }

    data = res.get("Data", [])
    to_create = []
    for elem in data:
        short_code = elem["Line_Short_Code"]
        line_ids = short_code_line_ids_map.get(short_code, None)

        assert isinstance(line_ids, list)
        if len(line_ids) > 0:
            for status, status_enum in key_status_map.items():
                to_create += [
                    LineVehicleStatusCountHistory(
                        snapshot_id=snapshot.id,
                        line_id=line_id,
                        status=status_enum,
                        count=elem[status],
                    )
                    for line_id in line_ids
                ]
        else:
            custom_line_obj, _ = SourceCustomLine.objects.get_or_create(
                source_id=source.id,
                name=short_code,
                defaults={
                    "source_id": source.id,
                    "name": short_code,
                },
            )

            for status, status_enum in key_status_map.items():
                to_create += [
                    LineVehicleStatusCountHistory(
                        snapshot_id=snapshot.id,
                        custom_line_id=custom_line_obj.id,
                        status=status_enum,
                        count=elem[status],
                    )
                ]

    LineVehicleStatusCountHistory.objects.bulk_create(
        to_create,
        ignore_conflicts=True,
    )
