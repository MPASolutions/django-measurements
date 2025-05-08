from django.core.management.base import BaseCommand

# from meteo.pgutils import load_data
from measurements.settings import SOURCE_AUTH
from measurements.sources.pessl import PesslAPI
from measurements.models import SourceType
from measurements.utils import get_serie, load_serie

PARAMETER_MAP = {"Precipitation|sum": "Precipitation", #
                 "Leaf Wetness|time": "LeafWet", #
                 "HC Air temperature|avg": "AtTemp", # http://vocab.nerc.ac.uk/collection/P01/current/CTMPZZ01/
                 "Air temperature, high precision|avg": "AtTemp",
                 "HC Relative humidity|avg": "RelHumidity", #http://vocab.nerc.ac.uk/collection/P01/current/CHUMZZ01/
                 "Relative humidity|avg": "RelHumidity",
                 "Dew Point|avg": "DewPoint", # http://vocab.nerc.ac.uk/collection/P01/current/CDEWZZ01/
                 "Wind speed|avg": "WindSpeed", # http://vocab.nerc.ac.uk/collection/P01/current/EWSBZZ01/
                 "Solar radiation|avg": "GlobalRad",
                 }

# parametri disponibili 8/5/25
# ['Air temperature, high precision|avg',
#  'Air temperature, high precision|max',
#  'Air temperature, high precision|min',
#  'Battery|last',
#  'DeltaT|avg',
#  'DeltaT|max',
#  'DeltaT|min',
#  'Dew Point|avg',
#  'Dew Point|min',
#  'EAG Soil moisture|avg',
#  'HC Air temperature|avg',
#  'HC Air temperature|max',
#  'HC Air temperature|min',
#  'HC Relative humidity|avg',
#  'HC Relative humidity|max',
#  'HC Relative humidity|min',
#  'Leaf Wetness|time',
#  'Precipitation|sum',
#  'Relative humidity|avg',
#  'Relative humidity|max',
#  'Relative humidity|min',
#  'Soil temperature|avg',
#  'Soil temperature|max',
#  'Soil temperature|min',
#  'Solar Panel|last',
#  'Solar radiation|avg',
#  'Sunshine duration|time',
#  'VPD|avg',
#  'VPD|min',
#  'Volumetric Ionic Content|avg',
#  'Wind direction|avg',
#  'Wind direction|last',
#  'Wind speed max|max',
#  'Wind speed|avg',
#  'Wind speed|max']


class Command(BaseCommand):
    help = "Command to import PESSL data"

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24
        )

    def handle(self, *args, **options):
        hours = options['hours']
        ps = SourceType.objects.get(code='pessl')
        for s in ps.station_set.filter  (status='active'):
            self.stdout.write("Loading station {} ... ".format(s), ending='')
            keys = SOURCE_AUTH['pessl'][s.network.code]
            pesslapi = PesslAPI(keys['public_key'],
                                keys['private_key'])
            df = pesslapi.get_df(s.code, hours)
            if df is not None and df.shape[0] > 0:
                for k, v in PARAMETER_MAP.items():
                    if k in df.columns:
                        serie = get_serie(s, v)
                        load_serie(df[k].copy(), serie.id)
                self.stdout.write("[OK]")
            else:
                self.stdout.write("[FAILED]")
