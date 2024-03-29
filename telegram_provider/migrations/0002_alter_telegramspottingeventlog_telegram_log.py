# Generated by Django 4.2.10 on 2024-03-18 21:43

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("telegram_provider", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="telegramspottingeventlog",
            name="telegram_log",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="telegram_logs",
                to="telegram_provider.telegramlogs",
            ),
        ),
    ]
