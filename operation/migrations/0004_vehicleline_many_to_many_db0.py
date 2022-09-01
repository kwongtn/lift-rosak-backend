# Generated by Django 4.1 on 2022-08-14 05:35

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operation", "0003_add_vehicle_vehicle_type_related_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="VehicleLine",
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
            ],
        ),
        migrations.AddField(
            model_name="line",
            name="vehicles_new",
            field=models.ManyToManyField(
                related_name="lines",
                through="operation.VehicleLine",
                to="operation.vehicle",
            ),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="lines_new",
            field=models.ManyToManyField(
                related_name="vehicles",
                through="operation.VehicleLine",
                to="operation.line",
            ),
        ),
        migrations.AlterField(
            model_name="vehicle",
            name="line",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="operation.line"
            ),
        ),
        migrations.AddField(
            model_name="vehicleline",
            name="line",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="operation.line"
            ),
        ),
        migrations.AddField(
            model_name="vehicleline",
            name="vehicle",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="operation.vehicle"
            ),
        ),
    ]