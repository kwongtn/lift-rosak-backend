# Generated by Django 4.1 on 2022-08-14 09:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operation", "0005_vehicleline_many_to_many_data"),
    ]

    operations = [
        migrations.RenameField(
            model_name="line",
            old_name="vehicles_new",
            new_name="vehicles",
        ),
        migrations.RemoveField(
            model_name="vehicle",
            name="line",
        ),
        migrations.RenameField(
            model_name="vehicle",
            old_name="lines_new",
            new_name="lines",
        ),
        migrations.AlterField(
            model_name="line",
            name="vehicles",
            field=models.ManyToManyField(
                related_name="vehicle_lines",
                through="operation.VehicleLine",
                to="operation.vehicle",
            ),
        ),
        migrations.AlterField(
            model_name="vehicle",
            name="lines",
            field=models.ManyToManyField(
                related_name="line_vehicles",
                through="operation.VehicleLine",
                to="operation.line",
            ),
        ),
    ]
