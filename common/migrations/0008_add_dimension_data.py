# Generated by Django 4.2.3 on 2023-07-16 16:23

from django.conf import settings
from django.db import migrations, models
from imgurpython import ImgurClient


def add_dimensions(apps, schema_editor):
    from common import models

    Media: models.Media = apps.get_model("common", "Media")
    client = ImgurClient(
        client_id=settings.IMGUR_CONSUMER_ID,
        client_secret=settings.IMGUR_CONSUMER_SECRET,
        access_token=settings.IMGUR_ACCESS_TOKEN,
        refresh_token=settings.IMGUR_ACCESS_TOKEN_REFRESH,
    )

    for media in Media.objects.all():
        print(f"Getting data for {media.file.name}")
        id = media.file.name.split(".")[0]
        res = client.get_image(f"{id}.json")

        print(f"Obtained data for {media.file.name} -- {res.width}x{res.height}")
        media.width = res.width
        media.height = res.height
        media.save()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("common", "0007_add_dimension_db"),
    ]

    operations = [
        migrations.RunPython(
            code=add_dimensions,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
