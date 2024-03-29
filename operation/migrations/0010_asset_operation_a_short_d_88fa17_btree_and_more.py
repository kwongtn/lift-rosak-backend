# Generated by Django 4.1 on 2022-08-28 09:32

import django.contrib.postgres.indexes
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("operation", "0009_alter_vehicleline_line_alter_vehicleline_vehicle"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="asset",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["short_description"], name="operation_a_short_d_88fa17_btree"
            ),
        ),
        migrations.AddIndex(
            model_name="asset",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["long_description"], name="operation_a_long_de_67af59_btree"
            ),
        ),
        migrations.AddIndex(
            model_name="line",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["code"], name="operation_l_code_370814_btree"
            ),
        ),
        migrations.AddIndex(
            model_name="line",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["display_name"], name="operation_l_display_e3a69a_btree"
            ),
        ),
        migrations.AddIndex(
            model_name="line",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["display_color"], name="operation_l_display_857380_btree"
            ),
        ),
        migrations.AddIndex(
            model_name="station",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["display_name"], name="operation_s_display_be1040_btree"
            ),
        ),
        migrations.AddIndex(
            model_name="stationline",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["display_name"], name="operation_s_display_38ef0e_btree"
            ),
        ),
        migrations.AddIndex(
            model_name="stationline",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["internal_representation"],
                name="operation_s_interna_a6acef_btree",
            ),
        ),
        migrations.AddIndex(
            model_name="vehicle",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["identification_no"], name="operation_v_identif_d2fca9_btree"
            ),
        ),
        migrations.AddIndex(
            model_name="vehicletype",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["internal_name"], name="operation_v_interna_f3d30b_btree"
            ),
        ),
        migrations.AddIndex(
            model_name="vehicletype",
            index=django.contrib.postgres.indexes.BTreeIndex(
                fields=["display_name"], name="operation_v_display_e0fd1e_btree"
            ),
        ),
    ]
