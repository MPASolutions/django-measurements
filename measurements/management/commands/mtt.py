from django.core.management.base import BaseCommand

# from meteo.pgutils import load_data
from measurements.settings import SOURCE_AUTH
from measurements.sources.mtt import MttAPI
from measurements.models import SourceType
from measurements.utils import StationLoadReport, get_serie, load_serie, write_load_outcome


PARAMETER_MAP = {"temperatura": "AtTemp",
                 "pioggia": "Precipitation",
                 # "d": "WindDirFrom",
                 "v": "WindSpeed",
                 "rh": "RelHumidity",
                 "rsg": "GlobalRad"
                 }


class Command(BaseCommand):
    help = "Command to import Meteotrentino data"

    def handle(self, *args, **options):
        ps = SourceType.objects.get(code='mtt')
        for s in ps.station_set.filter(status='active'):
            self.stdout.write("Loading station {} ... ".format(s), ending='')
            apiclient = MttAPI()
            df = apiclient.get_df(s.code)
            if df is not None and df.shape[0] > 0:
                # the provider keeps answering for a dead logger, serving the same old samples over
                # and over, so a non empty frame is not enough to call this station healthy
                report = StationLoadReport(label=str(s))
                for k, v in PARAMETER_MAP.items():
                    if k in df.columns:
                        serie = get_serie(s, v)
                        report.add(load_serie(df[k].copy(), serie.id))
                write_load_outcome(self, report)
            else:
                self.stdout.write(self.style.ERROR("[FAILED] no data returned by the provider"))