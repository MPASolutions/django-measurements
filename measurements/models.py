# import pandas as pd
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.contrib.postgres.fields import ArrayField
from django.utils.text import slugify
from django_pandas.io import read_frame
from psqlextra.manager import PostgresManager
from measurements import ureg, Q_
from pint.errors import UndefinedUnitError
import numpy as np

def validate_uom(value):
    if value is None:
        return value
    try:
        return ureg(value).units
    except UndefinedUnitError:
        pass
    raise ValidationError("The provided unit of measure ({}) is not identifiable. Please provide a valid name.".format(value))


class PhysicalParameter(models.Model):
    """The PhysicalParameter model is used to represent physical parameters with
    standard codes and labels. For example, the parameter 'HC Air Temperature' should
    point to a PhysicalParameter instance with code="AtTemp" and label="Air Temperature"
    """
    code = models.CharField(max_length=100)
    uri = models.URLField(
        blank=True,
        null=True,
        help_text="Reference to a controlled vocabulary (eg. NERC)",
    )
    label = models.CharField(max_length=150, blank=True, null=True)
    series_layer_options = models.JSONField(
        blank=True,
        null=True,
        help_text="Default options to use to render thisparameter in a map layer",
    )

    def __str__(self):
        return self.code


class Parameter(models.Model):
    code = models.CharField(max_length=100)
    uri = models.URLField(blank=True, null=True, help_text="Reference to a controlled vocabulary (eg. NERC)")
    label = models.CharField(max_length=150, blank=True, null=True)
    uom = models.CharField(max_length=25,
                           validators=[validate_uom],
                           help_text="unit of measure based on python-pint unit registry (eg. meter, kelvin)",
                           blank=True, null=True)
    physical_parameter = models.ForeignKey(
        PhysicalParameter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Reference to a standardized physical parameter",
    )

    objects = models.Manager()
    extra = PostgresManager()

    def __str__(self):
        if self.uom is None:
            return u'{}'.format(self.code)
        else:
            return u'{} ({})'.format(self.code, self.uom)


class Sensor(models.Model):
    code = models.CharField(max_length=100)
    label = models.CharField(max_length=150, blank=True, null=True)

    objects = models.Manager()
    extra = PostgresManager()

    def __str__(self):
        return u'{}'.format(self.label)


class LocationManager(models.Manager):
    def get_flatjson(self):
        data = []
        qs = super().get_queryset()
        for l in qs:
            r = {'key': slugify(l.label),
                 'latitute': l.geo.centroid.y,
                 'longitude': l.geo.centroid.x,
                 'name': l.label
                 }
            data.append(r)
        return data


class Location(models.Model):
    label = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    geo = models.PointField(srid=4326, null=True)
    elevation = models.IntegerField(null=True, blank=True)
    image = models.ImageField(null=True, blank=True)

    objects = LocationManager()
    extra = PostgresManager()

    def __str__(self):
        return u'{}'.format(self.label)


class Network(models.Model):
    code = models.CharField(max_length=100)
    label = models.CharField(max_length=150, blank=True, null=True)

    def __str__(self):
        if self.label is not None:
            return u'{}'.format(self.label)
        else:
            return u'{}'.format(self.code)


class SourceType(models.Model):
    code = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return u'{}'.format(self.code)


class Station(models.Model):
    code = models.CharField(max_length=100)
    label = models.CharField(max_length=150, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    image = models.ImageField(null=True, blank=True)
    network = models.ForeignKey(Network, on_delete=models.CASCADE, null=True, blank=True)
    # location has been moved directly within Series model
    # this location field should provide current Station location
    location = models.ForeignKey(Location, on_delete=models.CASCADE, null=True, blank=True)
    source = models.ForeignKey(SourceType, on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=255,
                              choices=[(i, i) for i in ['active', 'decomissioned', 'in maintenance']], default='active')
    parameters_mapping = models.ManyToManyField(Parameter, through='ParameterMapping')
    # this allows to override SourceType endpoint
    uri = models.URLField(blank=True, null=True, help_text="DataSource/Station endpoint")

    objects = models.Manager()
    extra = PostgresManager()

    def __str__(self):
        l = getattr(self, 'label') or getattr(self, 'code')
        n = getattr(self, 'network', '')
        return u'{} {}'.format(l, n)

    class Meta:
        verbose_name = "DataSource/Station"
        verbose_name_plural = "DataSources/Stations"


class ParameterMapping(models.Model):
    data_source = models.ForeignKey(Station, on_delete=models.CASCADE)
    source_parameter_label = models.CharField(max_length=64,
                                              help_text="Parameter label or layer name published by the data provider")
    source_parameter_uom = models.CharField(max_length=25,
                                            validators=[validate_uom],
                                            help_text="unit of measure based on python-pint unit registry (eg. meter, kelvin)",
                                            blank=True, null=True)
    parameter = models.ForeignKey(Parameter, on_delete=models.CASCADE)


class Serie(models.Model):
    station = models.ForeignKey(Station, on_delete=models.CASCADE)
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE)
    parameter = models.ForeignKey(Parameter, on_delete=models.CASCADE)
    height = models.FloatField(blank=True, null=True)
    location = models.ForeignKey(Location, on_delete=models.CASCADE, null=True, blank=True)
    # add below additional fields
    stats_mean = models.FloatField(blank=True, null=True)
    stats_outliers = ArrayField(models.IntegerField(), blank=True, null=True)

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
        return u'{} - {} - {}'.format(self.station, self.parameter, self.sensor.label)


class Measure(models.Model):
    id = models.BigAutoField(primary_key=True)
    serie = models.ForeignKey(Serie, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(db_index=True)
    value = models.FloatField()

    objects = models.Manager()
    extra = PostgresManager()

    class Meta:
        unique_together = ('serie', 'timestamp') #, 'value')
