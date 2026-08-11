from django.core.management.base import BaseCommand

# from meteo.pgutils import load_data
from measurements.settings import SOURCE_AUTH
from measurements.sources.davis import DavisAPI
from measurements.models import SourceType
from measurements.utils import StationLoadReport, get_serie, load_serie, write_load_outcome

PARAMETER_MAP = {"TempAria": "At_temp",
                 # "nasstemp": "At_temp_WetBulb",
                 # "UmidAriaRel": "RelHumidity",
                 "PntRugiada": "DewPoint",
                 "PressAtm": "AtPres",
                 "RadSol": "GlobalRad",
                 "VelVento": "WindSpeed",
                 "Precip": "Precipitation"
                 }

class Command(BaseCommand):
    help = "Command to import Davis data"

    def handle(self, *args, **options):
        ps = SourceType.objects.get(code='davis')
        for s in ps.station_set.filter(status='active'):
            self.stdout.write("Loading station {} ... ".format(s), ending='')
            davisapi = DavisAPI()
            df = davisapi.get_df(s.code, 5)
            if df is None or df.shape[0] == 0:
                self.stdout.write(self.style.ERROR("[FAILED] no data returned by the provider"))
                continue
            # the station keeps being served after the logger stops, with the same samples every
            # run, so the freshness of the data is the only thing that separates the two cases
            report = StationLoadReport(label=str(s))
            for k, v in PARAMETER_MAP.items():
                if k in df.columns:
                    serie = get_serie(s, v)
                    report.add(load_serie(df[k].copy(), serie.id))
            write_load_outcome(self, report)