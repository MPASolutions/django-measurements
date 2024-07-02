# Generated by Django 4.2.11 on 2024-06-28 15:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('measurements', '0022_parameter_physical_parameter'),
    ]

    operations = [
        migrations.AddField(
            model_name='physicalparameter',
            name='series_layer_options',
            field=models.JSONField(blank=True, help_text='Default options to use to render thisparameter in a map layer', null=True),
        ),
    ]
