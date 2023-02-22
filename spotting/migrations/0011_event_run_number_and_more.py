# Generated by Django 4.1.5 on 2023-02-12 16:55

import django.contrib.postgres.indexes
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("spotting", "0010_remove_event_spotting_event_value_relevant_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="run_number",
            field=models.CharField(blank=True, default=None, max_length=32, null=True),
        ),
        migrations.AddIndex(
            model_name="event",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["vehicle", "run_number", "-spotting_date"],
                name="spotting_ev_vehicle_446e00_btree",
            ),
        ),
    ]
