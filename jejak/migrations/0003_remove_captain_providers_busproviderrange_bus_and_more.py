# Generated by Django 4.1.5 on 2023-01-13 03:44

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jejak", "0002_trip_jejak_trip_trip_bus_provider_unique"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="captain",
            name="providers",
        ),
        migrations.AddField(
            model_name="busproviderrange",
            name="bus",
            field=models.ForeignKey(
                default=None,
                on_delete=django.db.models.deletion.PROTECT,
                to="jejak.bus",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="busproviderrange",
            name="provider",
            field=models.ForeignKey(
                default=None,
                on_delete=django.db.models.deletion.PROTECT,
                to="jejak.provider",
            ),
            preserve_default=False,
        ),
    ]
