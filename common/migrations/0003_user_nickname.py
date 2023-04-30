# Generated by Django 4.2 on 2023-04-29 10:15

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0002_user_badges"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="nickname",
            field=models.CharField(
                blank=True,
                default="",
                max_length=255,
            ),
        ),
    ]
