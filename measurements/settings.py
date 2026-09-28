import os

from django.conf import settings

BASE_DIR = os.path.dirname(os.path.realpath(__file__))

DEFAULT_SOURCE_AUTH = (
)

DEFAULT_DATABASE_ROUTING = 'default'

# Limits of the quality control applied by load_serie, keyed by parameter code or by physical
# parameter code (the parameter code wins, so a provider can be told apart from the quantity).
# min/max and spike are in the units of the parameter, spike_max_gap and persistence in seconds.
# The figures quoted below come from the measurements of 2026. See measurements.quality.
DEFAULT_QUALITY_CHECKS = {
    "AtTemp": {
        # absolute limits of WMO-No. 955 for air temperature
        "min": -80,
        "max": 60,
        # up and back within an hour: above 12 degrees only dropouts of broken sensors (to 0, to -40),
        # the largest real looking dips are summer afternoons of openmeteo at 9.9 and 10.2 degrees
        "spike": 12,
        "spike_max_gap": 3600,
        # identical for 12 hours happens on forecasts sampled every 6 hours, 18 only on dead sensors
        "persistence": 18 * 3600,
    },
    "RelHumidity": {
        # 100 plus the tolerance of capacitive sensors at saturation (fog readings up to 101.3)
        "min": 0,
        "max": 103,
        # below 1% readings pile up on dead sensors (0 and 0.01 for days), real lows go on above
        "suspect_min": 1,
    },
    "Precipitation": {
        "min": 0,
        # envelope of the world rainfall records, P = 422 * D ** 0.475 mm for D hours (Jennings)
        "envelope": (422, 0.475),
    },
}

SOURCE_AUTH = getattr(settings, 'MEASUREMENTS_SOURCE_AUTH', DEFAULT_SOURCE_AUTH)

DATABASE_ROUNTING = getattr(settings, 'MEASUREMENTS_DATABASE_ROUTING', DEFAULT_DATABASE_ROUTING)

QUALITY_CHECKS = getattr(settings, 'MEASUREMENTS_QUALITY_CHECKS', DEFAULT_QUALITY_CHECKS)
