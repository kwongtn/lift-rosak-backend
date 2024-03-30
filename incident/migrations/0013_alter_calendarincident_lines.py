# Generated by Django 4.2.10 on 2024-03-11 09:08

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operation", "0015_alter_line_display_color_vehicle_wheel_status"),
        ("incident", "0012_alter_calendarincidentchronology_source_url"),
    ]

    operations = [
        migrations.AlterField(
            model_name="calendarincident",
            name="lines",
            field=models.ManyToManyField(
                blank=True, related_name="incidents", to="operation.line"
            ),
        ),
    ]