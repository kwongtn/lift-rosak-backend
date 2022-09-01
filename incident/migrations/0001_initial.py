# Generated by Django 4.1 on 2022-08-31 16:11

import django.contrib.gis.db.models.fields
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("operation", "0010_asset_operation_a_short_d_88fa17_btree_and_more"),
        ("common", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="VehicleIncident",
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
                    "order",
                    models.PositiveIntegerField(
                        db_index=True, editable=False, verbose_name="order"
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
                ("date", models.DateField()),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("CRITICAL", "Critical"),
                            ("TRIVIA", "Trivia"),
                            ("STATUS", "Status"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "location",
                    django.contrib.gis.db.models.fields.PointField(
                        blank=True, default=None, null=True, srid=4326
                    ),
                ),
                ("title", models.CharField(default=None, max_length=64)),
                ("brief", models.CharField(default=None, max_length=256)),
                ("medias", models.ManyToManyField(blank=True, to="common.media")),
                (
                    "vehicle",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="operation.vehicle",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="StationIncident",
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
                    "order",
                    models.PositiveIntegerField(
                        db_index=True, editable=False, verbose_name="order"
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
                ("date", models.DateField()),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("CRITICAL", "Critical"),
                            ("TRIVIA", "Trivia"),
                            ("STATUS", "Status"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "location",
                    django.contrib.gis.db.models.fields.PointField(
                        blank=True, default=None, null=True, srid=4326
                    ),
                ),
                ("title", models.CharField(default=None, max_length=64)),
                ("brief", models.CharField(default=None, max_length=256)),
                ("medias", models.ManyToManyField(blank=True, to="common.media")),
                (
                    "station",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="operation.station",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
    ]