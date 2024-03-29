# Generated by Django 4.2.10 on 2024-03-11 09:08

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("incident", "0013_alter_calendarincident_lines"),
        ("operation", "0015_alter_line_display_color_vehicle_wheel_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="line",
            name="calendar_incidents",
            field=models.ManyToManyField(to="incident.calendarincident"),
        ),
        migrations.AddField(
            model_name="line",
            name="telegram_channel_id",
            field=models.TextField(blank=True, default=None, null=True, unique=True),
        ),
    ]
