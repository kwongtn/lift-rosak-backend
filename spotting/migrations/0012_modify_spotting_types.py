# Generated by Django 4.2 on 2023-04-28 13:06

from django.db import migrations, models

from spotting.enums import SpottingVehicleStatus
from spotting.models import Event


def fix_spotting_type(apps, schema_editor):
    compares = (
        (
            [SpottingVehicleStatus.NOT_SPOTTED, SpottingVehicleStatus.UNKNOWN],
            SpottingVehicleStatus.NOT_IN_SERVICE,
        ),
        (
            [SpottingVehicleStatus.MARRIED],
            SpottingVehicleStatus.IN_SERVICE,
        ),
    )

    to_update = []
    for statuses, target in compares:
        events = Event.objects.filter(status__in=statuses)
        for event in events:
            event.status = target
            to_update.append(event)

    Event.objects.bulk_update(to_update, ["status"])


class Migration(migrations.Migration):
    dependencies = [
        ("spotting", "0011_event_run_number_and_more"),
    ]

    operations = [
        migrations.RunPython(
            code=fix_spotting_type,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="event",
            name="status",
            field=models.CharField(
                choices=[
                    ("IN_SERVICE", "In Service"),
                    ("NOT_IN_SERVICE", "Not In Service"),
                    ("DECOMMISSIONED", "Decommissioned"),
                    ("TESTING", "Testing"),
                    ("NOT_SPOTTED", "Not Spotted"),
                    ("MARRIED", "Married"),
                    ("UNKNOWN", "Unknown"),
                ],
                max_length=32,
            ),
        ),
    ]