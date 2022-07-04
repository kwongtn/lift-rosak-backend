# Generated by Django 4.0.5 on 2022-07-04 15:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "operation",
            "0002_assetmedia_stationmedia_asset_medias_station_medias_and_more",
        ),
    ]

    operations = [
        migrations.RemoveField(
            model_name="stationline",
            name="display_name",
        ),
        migrations.AddField(
            model_name="line",
            name="stations",
            field=models.ManyToManyField(
                through="operation.StationLine", to="operation.station"
            ),
        ),
        migrations.AlterField(
            model_name="station",
            name="lines",
            field=models.ManyToManyField(
                through="operation.StationLine", to="operation.line"
            ),
        ),
    ]