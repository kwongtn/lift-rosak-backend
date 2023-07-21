# Generated by Django 4.2.3 on 2023-07-20 16:27

import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0009_alter_media_file"),
        ("incident", "0010_calendarincident_inaccurate_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="CalendarIncidentMedia",
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
                    "timestamp",
                    models.DateTimeField(blank=True, default=None, null=True),
                ),
                (
                    "calendar_incident",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="incident.calendarincident",
                    ),
                ),
                (
                    "media",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="common.media"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.RemoveField(
            model_name="calendarincident",
            name="medias",
        ),
        migrations.AddField(
            model_name="calendarincident",
            name="medias",
            field=models.ManyToManyField(
                blank=True,
                through="incident.CalendarIncidentMedia",
                to="common.media",
            ),
        ),
    ]
