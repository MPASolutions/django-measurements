from django.core.management.base import BaseCommand

from measurements.sources.cmems_wms import CMEMSWmsDataSource
from measurements.models import SourceType
from measurements.utils import StationLoadReport, get_serie, load_serie, write_load_outcome
from measurements import  ureg, Q_

class Command(BaseCommand):
    help = "Command to import CMEMS WMS data."

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30
        )
        parser.add_argument(
            '--daysgap',
            type=int,
            default=0
        )

    def handle(self, *args, **options):
        days = options['days']
        daysgap = options['daysgap']

        ps = SourceType.objects.get(code='cmems_wms')
        for station in ps.station_set.filter(status='active'):
            self.stdout.write("Loading DataSource/Station {} ... ".format(station))
            apiclient = CMEMSWmsDataSource(station.uri)

            self.stdout.write("\tLooking for registered layers/parameters ...")
            for pm in station.parametermapping_set.all():
                parameter = pm.parameter
                source_uom = pm.source_parameter_uom
                uom = parameter.uom
                print(source_uom, uom, parameter)
                layer = pm.source_parameter_label
                self.stdout.write("\tLooking for registered series ...")
                for series in station.serie_set.filter(parameter=parameter).all():
                    location = series.location
                    # print(series)
                    self.stdout.write(
                        "\tLoading series {}. Layer {}. Location {} ... ".format(series.id, layer, location),
                        ending=''
                    )
                    point = [location.geo.x, location.geo.y]

                    df = apiclient.get_df(layer, point, timedelta=days, timegap=daysgap)
                    # convert uom if needed
                    if uom is not None and source_uom is not None and uom != source_uom:
                        df['value'] = Q_(df.value.array, source_uom).to(uom).magnitude
                    if df.shape[0] > 0:
                        # rows alone say the service answered, not that the answer is current
                        report = StationLoadReport(label=str(series))
                        report.add(load_serie(df['value'].copy(), series.id))
                        write_load_outcome(self, report)
                    else:
                        self.stdout.write(self.style.ERROR("[FAILED] no data returned by the provider"))
