# Generated by Django 4.2.3 on 2023-07-12 21:56

import uuid

import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0004_remove_media_is_removed_alter_media_file"),
    ]

    operations = [
        migrations.CreateModel(
            name="TemporaryMedia",
            fields=[
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "id",
                    model_utils.fields.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("file", models.FileField(upload_to="temporary_media")),
                (
                    "upload_type",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "uploader",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="common.user"
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
