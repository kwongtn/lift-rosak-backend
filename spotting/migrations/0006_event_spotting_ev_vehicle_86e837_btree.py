# Generated by Django 4.1 on 2022-08-28 06:50

import django.contrib.postgres.indexes
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("spotting", "0005_alter_event_reporter_alter_event_vehicle"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="event",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["vehicle", "-spotting_date"],
                name="spotting_ev_vehicle_86e837_btree",
            ),
        ),
    ]
