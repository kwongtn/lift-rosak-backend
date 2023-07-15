import logging
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Q
from django.utils.timezone import now

from chartography.enums import DataSources
from chartography.models import LineVehicleStatusCountHistory, Snapshot, Source
from operation.enums import VehicleStatus
from operation.models import Line, VehicleLine
from rosak.celery import app as celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
async def aggregate_line_vehicle_status_mlptf_task(self, *args, **kwargs):
    source: Source = await Source.objects.aget(name=DataSources.MLPTF)

    # Get snapshot now, date would be previous day.
    # It is expected we do it at next day 5am.
    snapshot: Snapshot = await Snapshot.objects.acreate(
        date=now() - timedelta(days=1),
        source_id=source.id,
    )

    query_dict = defaultdict()
    async for line in Line.objects.all():
        for status in [i[0] for i in VehicleStatus.choices]:
            query_dict[f"{line.id}__{status}"] = Count(
                "id",
                filter=Q(
                    line_id=line.id,
                    vehicle__status=status,
                ),
            )

    stats = await VehicleLine.objects.aaggregate(**query_dict)

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

    return await LineVehicleStatusCountHistory.objects.abulk_create(create_objs)
