# Generated by Django 4.1 on 2022-09-01 16:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operation", "0010_asset_operation_a_short_d_88fa17_btree_and_more"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="stationline",
            constraint=models.UniqueConstraint(
                fields=("line", "internal_representation"),
                name="operation_stationline_unique_line_internal_representation",
            ),
        ),
    ]
