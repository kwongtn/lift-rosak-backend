# Generated by Django 4.2.3 on 2023-07-20 16:27

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0009_alter_media_file"),
    ]

    operations = [
        migrations.AlterField(
            model_name="temporarymedia",
            name="upload_type",
            field=models.CharField(
                choices=[
                    ("SPOTTING_EVENT", "Spotting Event"),
                    ("INCIDENT_CALENDAR_INCIDENT", "Incident Calendar Incident"),
                ],
                max_length=255,
            ),
        ),
    ]
