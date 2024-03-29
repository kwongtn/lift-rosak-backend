# Generated by Django 4.2.3 on 2023-07-16 21:06

from django.db import migrations

import common.imgur_field
import common.imgur_storage


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0008_add_dimension_data"),
    ]

    operations = [
        migrations.AlterField(
            model_name="media",
            name="file",
            field=common.imgur_field.ImgurField(
                height_field="height",
                storage=common.imgur_storage.ImgurStorage(),
                upload_to="rosak_local_kwongtn",
                width_field="width",
            ),
        ),
    ]
