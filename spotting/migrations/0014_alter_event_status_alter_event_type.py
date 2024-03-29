# Generated by Django 4.2.3 on 2023-07-12 00:56

import django_choices_field.fields
from django.db import migrations

import spotting.enums


class Migration(migrations.Migration):
    dependencies = [
        ("spotting", "0013_eventmedia_event_medias"),
    ]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="status",
            field=django_choices_field.fields.TextChoicesField(
                choices=[
                    ("IN_SERVICE", "In Service"),
                    ("NOT_IN_SERVICE", "Not In Service"),
                    ("DECOMMISSIONED", "Decommissioned"),
                    ("TESTING", "Testing"),
                    ("NOT_SPOTTED", "Not Spotted"),
                    ("MARRIED", "Married"),
                    ("UNKNOWN", "Unknown"),
                ],
                choices_enum=spotting.enums.SpottingVehicleStatus,
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="event",
            name="type",
            field=django_choices_field.fields.TextChoicesField(
                choices=[
                    ("DEPOT", "Depot"),
                    ("LOCATION", "Location"),
                    ("BETWEEN_STATIONS", "Between Stations"),
                    ("JUST_SPOTTING", "Just Spotting"),
                    ("AT_STATION", "At Station"),
                ],
                choices_enum=spotting.enums.SpottingEventType,
                max_length=32,
            ),
        ),
    ]
