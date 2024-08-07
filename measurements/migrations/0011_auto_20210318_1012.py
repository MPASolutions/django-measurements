# Generated by Django 2.2.3 on 2021-03-18 10:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('measurements', '0010_serie_location'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='station',
            options={'verbose_name': 'DataSource/Station', 'verbose_name_plural': 'DataSources/Stations'},
        ),
        migrations.AddField(
            model_name='station',
            name='uri',
            field=models.URLField(blank=True, help_text='DataSource/Station endpoint', null=True),
        ),
    ]
