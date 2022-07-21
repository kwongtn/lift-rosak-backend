# Generated by Django 4.0.6 on 2022-07-21 16:16

import colorfield.fields
import django.contrib.gis.db.models.fields
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("common", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Asset",
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
                (
                    "officialid",
                    models.CharField(
                        blank=True, default=None, max_length=64, null=True
                    ),
                ),
                (
                    "short_description",
                    models.CharField(blank=True, default="", max_length=96),
                ),
                ("long_description", models.TextField(blank=True, default="")),
                (
                    "asset_type",
                    models.TextField(
                        choices=[("ESCALATOR", "Escalator"), ("LIFT", "Lift")]
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Line",
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
                ("code", models.CharField(max_length=32, unique=True)),
                ("display_name", models.TextField()),
                (
                    "display_color",
                    colorfield.fields.ColorField(
                        default="#FFFFFF", image_field=None, max_length=18, samples=None
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Station",
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
                ("display_name", models.TextField()),
                (
                    "location",
                    django.contrib.gis.db.models.fields.PointField(
                        blank=True, default=None, null=True, srid=4326
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="StationMedia",
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
                    "media",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="common.media"
                    ),
                ),
                (
                    "station",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="operation.station",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="StationLine",
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
                ("display_name", models.TextField()),
                (
                    "internal_representation",
                    models.CharField(
                        blank=True, default=None, max_length=32, null=True, unique=True
                    ),
                ),
                (
                    "line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="operation.line"
                    ),
                ),
                (
                    "station",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="operation.station",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="station",
            name="lines",
            field=models.ManyToManyField(
                through="operation.StationLine", to="operation.line"
            ),
        ),
        migrations.AddField(
            model_name="station",
            name="medias",
            field=models.ManyToManyField(
                through="operation.StationMedia", to="common.media"
            ),
        ),
        migrations.AddField(
            model_name="line",
            name="stations",
            field=models.ManyToManyField(
                through="operation.StationLine", to="operation.station"
            ),
        ),
        migrations.CreateModel(
            name="AssetMedia",
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
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="operation.asset",
                    ),
                ),
                (
                    "media",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="common.media"
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="asset",
            name="medias",
            field=models.ManyToManyField(
                through="operation.AssetMedia", to="common.media"
            ),
        ),
        migrations.AddField(
            model_name="asset",
            name="station",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="operation.station"
            ),
        ),
        migrations.AddField(
            model_name="asset",
            name="status",
            field=models.CharField(
                choices=[
                    ("UNDER_MAINTENANCE", "Under Maintenance"),
                    ("IN_OPERATION", "In Operation"),
                ],
                default="IN_OPERATION",
                max_length=32,
            ),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name="VehicleType",
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
                ("display_name", models.CharField(max_length=64)),
                ("description", models.TextField(blank=True, default="")),
                (
                    "internal_name",
                    models.CharField(
                        blank=True, default=None, max_length=16, null=True
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Vehicle",
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
                ("identification_no", models.CharField(max_length=16)),
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
                ("notes", models.TextField(blank=True, default="")),
                (
                    "line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="operation.line"
                    ),
                ),
                (
                    "vehicle_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="operation.vehicletype",
                    ),
                ),
                (
                    "in_service_since",
                    models.DateField(blank=True, default=None, null=True),
                ),
            ],
        ),
    ]
