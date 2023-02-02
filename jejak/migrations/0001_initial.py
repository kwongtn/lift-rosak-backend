# Generated by Django 4.1.5 on 2023-02-02 13:50

import django.contrib.gis.db.models.fields
import django.contrib.postgres.fields.ranges
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Accessibility",
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
                ("identifier", models.CharField(max_length=64, unique=True)),
                ("details", models.TextField(blank=True, default="")),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Bus",
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
                ("identifier", models.CharField(max_length=64, unique=True)),
                ("details", models.TextField(blank=True, default="")),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="BusStop",
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
                ("identifier", models.CharField(max_length=64, unique=True)),
                ("details", models.TextField(blank=True, default="")),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="BusType",
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
                ("title", models.TextField(blank=True, default="")),
                ("description", models.TextField(blank=True, default="")),
            ],
        ),
        migrations.CreateModel(
            name="Captain",
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
                ("identifier", models.CharField(max_length=64, unique=True)),
                ("details", models.TextField(blank=True, default="")),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="CaptainProviderRange",
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
                    "dt_range",
                    django.contrib.postgres.fields.ranges.DateTimeRangeField(
                        default_bounds="[]"
                    ),
                ),
                (
                    "captain",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.captain"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="EngineStatus",
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
                ("identifier", models.CharField(max_length=64, unique=True)),
                ("details", models.TextField(blank=True, default="")),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Provider",
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
                ("identifier", models.CharField(max_length=64, unique=True)),
                ("details", models.TextField(blank=True, default="")),
                (
                    "captains",
                    models.ManyToManyField(
                        through="jejak.CaptainProviderRange", to="jejak.captain"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Route",
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
                ("identifier", models.CharField(max_length=64)),
                ("details", models.TextField(blank=True, default="")),
                (
                    "provider",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="jejak.provider",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Trip",
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
                ("identifier", models.CharField(max_length=64)),
                ("details", models.TextField(blank=True, default="")),
                (
                    "bus",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.bus"
                    ),
                ),
                (
                    "provider",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.provider"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TripRev",
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
                ("identifier", models.CharField(max_length=64, unique=True)),
                ("details", models.TextField(blank=True, default="")),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="TripRevBusRange",
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
                    "dt_range",
                    django.contrib.postgres.fields.ranges.DateTimeRangeField(
                        default_bounds="[]"
                    ),
                ),
                (
                    "bus",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.bus"
                    ),
                ),
                (
                    "trip_rev",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.triprev"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="TripRange",
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
                    "dt_range",
                    django.contrib.postgres.fields.ranges.DateTimeRangeField(
                        default_bounds="[]"
                    ),
                ),
                (
                    "trip",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.trip"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="BusRouteRange",
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
                    "dt_range",
                    django.contrib.postgres.fields.ranges.DateTimeRangeField(
                        default_bounds="[]"
                    ),
                ),
                (
                    "bus",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.bus"
                    ),
                ),
                (
                    "route",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.route"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Location",
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
                ("dt_received", models.DateTimeField(editable=False)),
                ("dt_gps", models.DateTimeField(editable=False)),
                ("location", django.contrib.gis.db.models.fields.PointField(srid=4326)),
                ("dir", models.CharField(blank=True, max_length=5, null=True)),
                ("speed", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("angle", models.PositiveSmallIntegerField(blank=True, null=True)),
                (
                    "bus",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.bus"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="EngineStatusBusRange",
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
                    "dt_range",
                    django.contrib.postgres.fields.ranges.DateTimeRangeField(
                        default_bounds="[]"
                    ),
                ),
                (
                    "bus",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.bus"
                    ),
                ),
                (
                    "engine_status",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="jejak.enginestatus",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="captainproviderrange",
            name="provider",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="jejak.provider"
            ),
        ),
        migrations.CreateModel(
            name="CaptainBusRange",
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
                    "dt_range",
                    django.contrib.postgres.fields.ranges.DateTimeRangeField(
                        default_bounds="[]"
                    ),
                ),
                (
                    "bus",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.bus"
                    ),
                ),
                (
                    "captain",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.captain"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="BusStopBusRange",
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
                    "dt_range",
                    django.contrib.postgres.fields.ranges.DateTimeRangeField(
                        default_bounds="[]"
                    ),
                ),
                (
                    "bus",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.bus"
                    ),
                ),
                (
                    "bus_stop",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.busstop"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="BusProviderRange",
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
                    "dt_range",
                    django.contrib.postgres.fields.ranges.DateTimeRangeField(
                        default_bounds="[]"
                    ),
                ),
                (
                    "bus",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.bus"
                    ),
                ),
                (
                    "provider",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.provider"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="bus",
            name="type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="jejak.bustype",
            ),
        ),
        migrations.CreateModel(
            name="AccessibilityBusRange",
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
                    "dt_range",
                    django.contrib.postgres.fields.ranges.DateTimeRangeField(
                        default_bounds="[]"
                    ),
                ),
                (
                    "accessibility",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="jejak.accessibility",
                    ),
                ),
                (
                    "bus",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="jejak.bus"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="route",
            constraint=models.UniqueConstraint(
                fields=("identifier", "provider"),
                name="jejak_route_unique_identifier_per_provider",
            ),
        ),
        migrations.AddConstraint(
            model_name="trip",
            constraint=models.UniqueConstraint(
                fields=("identifier", "bus", "provider"),
                name="jejak_trip_trip_bus_provider_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="location",
            constraint=models.UniqueConstraint(
                fields=("dt_received", "dt_gps", "bus"),
                name="jejak_location_unique_received_gps_time_bus",
            ),
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE public.jejak_location DROP CONSTRAINT jejak_location_pkey;
                ALTER TABLE public.jejak_location ADD CONSTRAINT jejak_location_pkey PRIMARY KEY (id, dt_gps);
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
                SELECT create_hypertable('jejak_location', 'dt_gps', chunk_time_interval => INTERVAL '1 day');
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
