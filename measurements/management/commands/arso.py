from django.core.management.base import BaseCommand

# from meteo.pgutils import load_data
from measurements.settings import SOURCE_AUTH
from measurements.sources.arso import ArsoAPI, ARSO_PARAMS
from measurements.models import SourceType
from measurements.utils import StationLoadReport, get_serie, load_serie, write_load_outcome


class Command(BaseCommand):
    help = "Command to import IOC sea level data"

    def handle(self, *args, **options):
        ps = SourceType.objects.get(code='arso')
        for s in ps.station_set.filter(status='active'):
            self.stdout.write("Loading station {} ... ".format(s), ending='')
            apiclient = ArsoAPI()
            df = apiclient.get_df(s.code)
            if df is None:
                self.stdout.write(self.style.ERROR("[FAILED] no data returned by the provider"))
                continue
            # a silent station is served exactly like a working one, only with older samples
            report = StationLoadReport(label=str(s))
            for k, v in ARSO_PARAMS.items():
                if v in df.columns:
                    serie = get_serie(s, v)
                    report.add(load_serie(df[v].copy(), serie.id))
            write_load_outcome(self, report)
