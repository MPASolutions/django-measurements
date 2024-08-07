# Generated by Django 4.2.11 on 2024-06-28 10:22

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('measurements', '0021_physicalparameter'),
    ]

    operations = [
        migrations.AddField(
            model_name='parameter',
            name='physical_parameter',
            field=models.ForeignKey(blank=True, help_text='Reference to a standardized physical parameter', null=True, on_delete=django.db.models.deletion.SET_NULL, to='measurements.physicalparameter'),
        ),
    ]
