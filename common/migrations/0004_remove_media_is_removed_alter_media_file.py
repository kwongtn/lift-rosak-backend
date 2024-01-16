# Generated by Django 4.2.1 on 2023-05-28 19:15

from django.conf import settings
from django.db import migrations, models

import common.imgur_storage


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0003_user_nickname"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="media",
            name="is_removed",
        ),
        migrations.AlterField(
            model_name="media",
            name="file",
            field=models.ImageField(
                storage=common.imgur_storage.ImgurStorage(),
                upload_to=settings.IMGUR_ALBUM,
            ),
        ),
    ]
