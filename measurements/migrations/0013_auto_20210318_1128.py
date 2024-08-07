# Generated by Django 2.2.3 on 2021-03-18 11:28

from django.db import migrations

def load_sources(apps, schema_editor):
    SourceType = apps.get_model('measurements', 'SourceType')
    SourceType.objects.create(code="cmems_wms")

class Migration(migrations.Migration):

    dependencies = [
        ('measurements', '0012_auto_20210318_1121'),
    ]

    operations = [
        migrations.RunPython(load_sources)
    ]