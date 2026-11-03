"""Tests for the explicit errors logged by the sources when a provider fails."""

import hashlib
import hmac
import json
from io import StringIO
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from urllib3.connection import HTTPConnection
from urllib3.exceptions import ConnectTimeoutError, MaxRetryError, NewConnectionError

from measurements.models import Network, SourceType, Station
from measurements.sources.arso import ArsoAPI
from measurements.sources.davis import DavisAPI
from measurements.sources.elmed import ElmedAPI
from measurements.sources.ioc import IocAPI
from measurements.sources.mtt import MttAPI
from measurements.sources.pessl import API_V2, PesslAPI

REQUESTS_GET = "measurements.sources.base.requests.get"
SOURCES_LOGGER = "measurements.sources.base"

# trimmed answer of FieldClimate v2 for station 00203A26, account in Italian
PESSL_V2_BODY = json.dumps({
    "dates": ["2026-11-03 14:00:00", "2026-11-03 15:00:00"],
    "data": [
        {"name": "Pioggia", "name_original": "Precipitation", "aggr": ["sum"], "values": {"sum": [0, 0.2]}},
        {"name": "Air temperature, high precision", "name_original": "Air temperature, high precision",
         "aggr": ["avg", "max", "min"], "values": {"avg": [10.5, 9.81], "max": [10.8, 9.99], "min": [9.99, 9.57]}},
        {"name": "Midnight", "type": "Calculation", "unit": False, "values": {"result": [None, None]}},
    ],
}).encode()


def make_response(body: bytes = b"", status_code: int = 200, url: str = "http://example.org/data") -> requests.Response:
    """Response as requests builds it, with the given body and status."""
    response = requests.Response()
    response.status_code = status_code
    response._content = body
    response.url = url
    response.encoding = "utf-8"
    return response


def make_network_error(error_class: type, url: str, message: str, reason_class: type) -> requests.RequestException:
    """Network error shaped as requests raises it, with the urllib3 reason inside a MaxRetryError."""
    connection = HTTPConnection("example.org")
    reason = reason_class(connection, message)
    return error_class(MaxRetryError(None, url, reason=reason))


class DownloadErrorsTests(SimpleTestCase):
    """Every failure of a provider ends in one explicit ERROR record and a None result."""

    def test_pessl_empty_body(self):
        with patch(REQUESTS_GET, return_value=make_response(url="https://api.fieldclimate.com/pretty/x")):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = PesslAPI("public", "private").get_df("00203A5B", 24)
        self.assertIsNone(df)
        self.assertEqual(logs.output, [
            "ERROR:measurements.sources.base:pessl: station 00203A5B not downloaded: api.fieldclimate.com "
            "answered HTTP 200 with an empty body"
        ])

    def test_pessl_body_not_json(self):
        response = make_response(b"<html>maintenance</html>", url="https://api.fieldclimate.com/pretty/x")
        with patch(REQUESTS_GET, return_value=response):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = PesslAPI("public", "private").get_df("00203A5B", 24)
        self.assertIsNone(df)
        self.assertIn("answered HTTP 200 with a body that is not JSON, body: '<html>maintenance</html>'",
                      logs.output[0])

    def test_pessl_json_without_data(self):
        response = make_response(b'{"message": "Station not found"}', url="https://api.fieldclimate.com/pretty/x")
        with patch(REQUESTS_GET, return_value=response):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = PesslAPI("public", "private").get_df("00203A5B", 24)
        self.assertIsNone(df)
        self.assertIn("not the JSON with the data and dates keys", logs.output[0])

    def test_mtt_connect_timeout(self):
        url = "http://dati.meteotrentino.it/service.asmx/ultimiDatiStazione?codice=T0118"
        error = make_network_error(requests.ConnectTimeout, url, "timed out", ConnectTimeoutError)
        with patch(REQUESTS_GET, side_effect=error) as get:
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = MttAPI().get_df("T0118")
        self.assertIsNone(df)
        self.assertEqual(get.call_args.kwargs["timeout"], 60)
        self.assertEqual(logs.output, [
            "ERROR:measurements.sources.base:mtt: station T0118 not downloaded: dati.meteotrentino.it "
            "unreachable, no connection within 60 s"
        ])

    def test_mtt_read_timeout(self):
        with patch(REQUESTS_GET, side_effect=requests.ReadTimeout()):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                MttAPI().get_df("T0118")
        self.assertIn("dati.meteotrentino.it accepted the connection but sent no data within 60 s", logs.output[0])

    def test_mtt_http_error(self):
        with patch(REQUESTS_GET, return_value=make_response(b"Service Unavailable", status_code=503)):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = MttAPI().get_df("T0118")
        self.assertIsNone(df)
        self.assertIn("answered HTTP 503, body: 'Service Unavailable'", logs.output[0])

    def test_mtt_body_not_xml(self):
        with patch(REQUESTS_GET, return_value=make_response(b"<html><body>error")):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = MttAPI().get_df("T0118")
        self.assertIsNone(df)
        self.assertIn("answered HTTP 200 with a body that is not XML", logs.output[0])

    def test_elmed_connection_error_hides_the_key(self):
        url = "http://www.elmedweb.com/MeteoWeb/download/download.php?auth=SECRETKEY"
        error = make_network_error(requests.ConnectionError, url,
                                   "Failed to establish a new connection: [Errno 111] Connection refused",
                                   NewConnectionError)
        with patch(REQUESTS_GET, side_effect=error):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = ElmedAPI(None, "SECRETKEY").get_df("1234", 24)
        self.assertIsNone(df)
        self.assertNotIn("SECRETKEY", logs.output[0])
        self.assertIn("www.elmedweb.com unreachable (Failed to establish a new connection: [Errno 111] "
                      "Connection refused)", logs.output[0])

    def test_elmed_body_not_csv(self):
        response = make_response(b"Error Database constructor",
                                 url="http://www.elmedweb.com/MeteoWeb/download/download.php?auth=SECRETKEY")
        with patch(REQUESTS_GET, return_value=response):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = ElmedAPI(None, "SECRETKEY").get_df("1234", 24)
        self.assertIsNone(df)
        self.assertNotIn("SECRETKEY", logs.output[0])
        self.assertIn("not a CSV starting with the Datum header, body: 'Error Database constructor'", logs.output[0])

    def test_davis_short_rows(self):
        with patch(REQUESTS_GET, return_value=make_response(b"12.00|01/11/2026|8.5\n")):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = DavisAPI().get_df("station1", 5)
        self.assertIsNone(df)
        self.assertIn("not rows of 59 pipe separated fields", logs.output[0])

    def test_ioc_page_without_table(self):
        with patch(REQUESTS_GET, return_value=make_response(b"<html><body>No data</body></html>")):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = IocAPI().get_df("trst")
        self.assertIsNone(df)
        self.assertIn("ioc: station trst not downloaded", logs.output[0])
        self.assertIn("not a page with the data table", logs.output[0])

    def test_arso_unreachable(self):
        with patch(REQUESTS_GET, side_effect=requests.ConnectionError()):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = ArsoAPI().get_df("5030")
        self.assertIsNone(df)
        self.assertIn("arso: station 5030 not downloaded: www.arso.gov.si unreachable (ConnectionError)",
                      logs.output[0])

    def test_same_template_for_every_station(self):
        """Sentry groups by message template: two stations with the same cause must share it."""
        with patch(REQUESTS_GET, return_value=make_response()):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                MttAPI().get_df("T0118")
                MttAPI().get_df("T0129")
        self.assertEqual(logs.records[0].msg, logs.records[1].msg)
        self.assertNotEqual(logs.records[0].getMessage(), logs.records[1].getMessage())


class CommandsKeepGoingTests(TestCase):
    """A station that fails no longer stops the command: the others are still downloaded."""

    databases = {"default", "measurements"}

    def create_stations(self, source_code: str) -> None:
        """Two active stations of the given source."""
        # the source types come with the migrations
        source, created = SourceType.objects.get_or_create(code=source_code)
        Station.objects.create(code="A1", source=source)
        Station.objects.create(code="B2", source=source)

    def test_mtt_all_stations_unreachable(self):
        self.create_stations("mtt")
        with patch(REQUESTS_GET, side_effect=requests.ConnectTimeout()) as get:
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                call_command("mtt", stdout=StringIO())
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(logs.output), 2)

    def test_davis_all_stations_unreachable(self):
        self.create_stations("davis")
        with patch(REQUESTS_GET, side_effect=requests.ConnectTimeout()) as get:
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                call_command("davis", stdout=StringIO())
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(logs.output), 2)


class PesslV2Tests(SimpleTestCase):
    """API v2 is chosen per network and gives the same columns as the v0 pretty route."""

    def test_v2_columns_use_the_english_names(self):
        with patch(REQUESTS_GET, return_value=make_response(PESSL_V2_BODY)):
            df = PesslAPI("public", "private", api_version=API_V2).get_df("00203A26", 2)
        self.assertEqual(list(df.columns), [
            "Precipitation|sum",
            "Air temperature, high precision|avg",
            "Air temperature, high precision|max",
            "Air temperature, high precision|min",
            "Midnight|result",
        ])
        self.assertEqual(df["Precipitation|sum"].tolist(), [0, 0.2])
        self.assertEqual(str(df.index.tz), "Etc/GMT-1")

    def test_v2_route_and_signature(self):
        with patch(REQUESTS_GET, return_value=make_response(PESSL_V2_BODY)) as get:
            PesslAPI("public", "private", api_version=API_V2).get_df("00203A26", 24)
        self.assertEqual(get.call_args.args[0], "https://api.fieldclimate.com/v2/data/00203A26/raw/last/24")
        headers = get.call_args.kwargs["headers"]
        self.assertNotIn("Date", headers)
        # the signed route has no version prefix
        message = "GET/data/00203A26/raw/last/24{}public".format(headers["Request-Date"]).encode()
        signature = hmac.new(b"private", message, hashlib.sha256).hexdigest()
        self.assertEqual(headers["Authorization"], "hmac public:{}".format(signature))
        self.assertNotIn("verify", get.call_args.kwargs)

    def test_v0_is_the_default(self):
        with patch(REQUESTS_GET, return_value=make_response(url="https://api.fieldclimate.com/pretty/x")) as get:
            with self.assertLogs(SOURCES_LOGGER, "ERROR"):
                PesslAPI("public", "private").get_df("00203A26", 24)
        self.assertEqual(get.call_args.args[0], "https://api.fieldclimate.com/pretty/00203A26/raw/last/24")
        self.assertIn("Date", get.call_args.kwargs["headers"])

    def test_v2_data_not_a_list(self):
        body = b'{"dates": [], "data": {"1": {}}}'
        with patch(REQUESTS_GET, return_value=make_response(body, url="https://api.fieldclimate.com/v2/data/x")):
            with self.assertLogs(SOURCES_LOGGER, "ERROR") as logs:
                df = PesslAPI("public", "private", api_version=API_V2).get_df("00203A26", 24)
        self.assertIsNone(df)
        self.assertIn("not the JSON with the data list and the dates key", logs.output[0])


class PesslCommandApiVersionTests(TestCase):
    """The command reads the API version of each network from the configuration, v0 when it is missing."""

    databases = {"default", "measurements"}

    def test_api_version_per_network(self):
        source, created = SourceType.objects.get_or_create(code="pessl")
        Station.objects.create(code="FER1", source=source, network=Network.objects.create(code="ferrari"))
        Station.objects.create(code="LAV1", source=source, network=Network.objects.create(code="lavis"))
        auth = {"pessl": {
            "ferrari": {"public_key": "p1", "private_key": "k1", "api_version": "v2"},
            "lavis": {"public_key": "p2", "private_key": "k2"},
        }}
        with patch("measurements.management.commands.pessl.SOURCE_AUTH", auth):
            with patch(REQUESTS_GET, return_value=make_response()) as get:
                with self.assertLogs(SOURCES_LOGGER, "ERROR"):
                    call_command("pessl", stdout=StringIO())
        urls = sorted(call.args[0] for call in get.call_args_list)
        self.assertEqual(urls, [
            "https://api.fieldclimate.com/pretty/LAV1/raw/last/24",
            "https://api.fieldclimate.com/v2/data/FER1/raw/last/24",
        ])
