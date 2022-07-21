# Generated by Django 4.0.6 on 2022-07-10 13:05

import django.contrib.gis.db.models.fields
import django.db.models.deletion
import django.db.models.expressions
import django.utils.timezone
import model_utils.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("common", "0001_initial"),
        ("operation", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Event",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("spotting_date", models.DateField()),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("IN_SERVICE", "In Service"),
                            ("NOT_SPOTTED", "Not Spotted"),
                            ("DECOMMISSIONED", "Decommissioned"),
                            ("TESTING", "Testing"),
                            ("UNKNOWN", "Unknown"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("DEPOT", "Depot"),
                            ("LOCATION", "Location"),
                            ("BETWEEN_STATIONS", "Between Stations"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "location",
                    django.contrib.gis.db.models.fields.PointField(
                        blank=True, default=None, null=True, srid=4326
                    ),
                ),
                (
                    "destination_station",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="destination_station_event",
                        to="operation.station",
                    ),
                ),
                (
                    "origin_station",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="origin_station_event",
                        to="operation.station",
                    ),
                ),
                (
                    "reporter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="common.user"
                    ),
                ),
                (
                    "vehicle",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="operation.vehicle",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="event",
            constraint=models.CheckConstraint(
                check=models.Q(
                    models.Q(
                        ("type", "BETWEEN_STATIONS"),
                        ("origin_station__isnull", False),
                        ("destination_station__isnull", False),
                        ("location__isnull", True),
                        models.Q(
                            (
                                "origin_station",
                                django.db.models.expressions.F("destination_station"),
                            ),
                            _negated=True,
                        ),
                        models.Q(
                            (
                                "destination_station",
                                django.db.models.expressions.F("origin_station"),
                            ),
                            _negated=True,
                        ),
                    ),
                    models.Q(
                        ("type", "LOCATION"),
                        ("origin_station__isnull", True),
                        ("destination_station__isnull", True),
                        ("location__isnull", False),
                    ),
                    models.Q(
                        ("type", "DEPOT"),
                        ("origin_station__isnull", True),
                        ("destination_station__isnull", True),
                        ("location__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="spotting_event_value_relevant",
            ),
        ),
    ]
