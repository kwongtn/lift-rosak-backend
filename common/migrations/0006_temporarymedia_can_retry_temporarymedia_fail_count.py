# Generated by Django 4.2.3 on 2023-07-15 11:17

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0005_temporarymedia"),
    ]

    operations = [
        migrations.AddField(
            model_name="temporarymedia",
            name="can_retry",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="temporarymedia",
            name="fail_count",
            field=models.IntegerField(default=0),
        ),
    ]