# import pandas as pd
from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from django_pandas.io import read_frame
from psqlextra.manager import PostgresManager

import numpy as np


class Parameter(models.Model):
    code = models.CharField(max_length=100, blank=True, null=True)
    uri = models.URLField(blank=True, null=True)
    label = models.CharField(max_length=150)

    objects = models.Manager()
    extra = PostgresManager()

    def __str__(self):
        return u'{}'.format(self.label)


class Sensor(models.Model):
    code = models.CharField(max_length=100)
    label = models.CharField(max_length=150, blank=True, null=True)

    objects = models.Manager()
    extra = PostgresManager()

    def __str__(self):
        return u'{}'.format(self.label)


class Location(models.Model):
    label = models.CharField(max_length=150)
    geo = models.PointField(srid=4326, null=True)

    objects = models.Manager()
    extra = PostgresManager()

    def __str__(self):
        return u'{}'.format(self.label)


class Network(models.Model):
    code = models.CharField(max_length=100)
    label = models.CharField(max_length=150, blank=True, null=True)

    def __str__(self):
        return u'{}'.format(self.label)


class SourceType(models.Model):
    code = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return u'{}'.format(self.code)


class Station(models.Model):
    code = models.CharField(max_length=100)
    label = models.CharField(max_length=150, null=True, blank=True)
    network = models.ForeignKey(Network, on_delete=models.CASCADE, null=True, blank=True)
    location = models.ForeignKey(Location, on_delete=models.CASCADE, null=True, blank=True)
    #TODO: not sure if source should be in Staton or Serie
    source = models.ForeignKey(SourceType, on_delete=models.CASCADE, null=True, blank=True)

    objects = models.Manager()
    extra = PostgresManager()

    def __str__(self):
        return u'{}'.format(self.code)


class Serie(models.Model):
    station = models.ForeignKey(Station, on_delete=models.CASCADE)
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE)
    parameter = models.ForeignKey(Parameter, on_delete=models.CASCADE)

    # add below additional fields
    stats_mean = models.FloatField(null=True)
    stats_outliers = ArrayField(models.IntegerField(), null=True)

    objects = models.Manager()
    extra = PostgresManager()

    def set_mean(self, threshold=5):
        df = read_frame(Measure.objects.filter(serie=self),
                        index_col='timestamp')

        df['pandas'] = df['value'].rolling(window=5, center=True).median().fillna(method='bfill').fillna(method='ffill')

        difference = np.abs(df['value'] - df['pandas'])
        outlier_idx = difference > threshold

        # print df.loc[outlier_idx, 'value'].shape
        self.stats_mean = df.loc[~outlier_idx, 'value'].mean()
        self.save()
        return self.stats_mean

    def __str__(self):
        return u'{} - {} - {}'.format(self.location.label, self.parameter.label, self.sensor.label)


class Measure(models.Model):
    serie = models.ForeignKey(Serie, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(db_index=True)
    value = models.FloatField()

    objects = models.Manager()
    extra = PostgresManager()