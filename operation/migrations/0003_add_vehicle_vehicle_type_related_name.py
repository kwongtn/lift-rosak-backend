# Generated by Django 4.0.6 on 2022-07-28 12:28

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operation", "0002_alter_asset_options_alter_line_options_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vehicle",
            name="vehicle_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="vehicles",
                to="operation.vehicletype",
            ),
        ),
    ]
