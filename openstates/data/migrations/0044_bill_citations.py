# Generated by Django 3.2.2 on 2021-11-08 20:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "data",
            "0043_legislativesession_active",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="bill",
            name="citations",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
