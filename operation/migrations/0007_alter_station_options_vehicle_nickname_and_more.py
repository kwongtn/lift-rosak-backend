# Generated by Django 4.1 on 2022-08-27 12:53

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operation", "0006_vehicleline_many_to_many_db1"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="station",
            options={"ordering": ["display_name"]},
        ),
        migrations.AddField(
            model_name="vehicle",
            name="nickname",
            field=models.CharField(blank=True, default=None, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name="vehicletype",
            name="internal_name",
            field=models.CharField(
                blank=True, default=None, max_length=16, null=True, unique=True
            ),
        ),
    ]
