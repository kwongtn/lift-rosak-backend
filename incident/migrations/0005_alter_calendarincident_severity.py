# Generated by Django 4.2.1 on 2023-05-10 17:09

from django.db import migrations, models

from incident.models import CalendarIncident


def fix_incident_severity(apps, schema_editor):
    CalendarIncident.objects.filter(severity="CRITICAL").update(severity="MAJOR")
    CalendarIncident.objects.filter(severity="MILESTONE").update(severity="OTHERS")


class Migration(migrations.Migration):
    dependencies = [
        ("incident", "0004_calendarincidentcategory_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="calendarincident",
            name="severity",
            field=models.CharField(
                choices=[
                    ("MAJOR", "Major"),
                    ("MINOR", "Minor"),
                    ("MILESTONE", "Milestone"),
                ],
                max_length=16,
            ),
        ),
        migrations.RunPython(
            code=fix_incident_severity,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
