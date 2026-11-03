# Source classes should not include reference to django
# This will facilitate use of functionalities within other packages/projects
# Django-related tasks (eg. uom conversion, fieldname mapping) should be moved
# into utilis or management commands
import logging
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

# a provider that accepts the connection and then stays silent would otherwise hold the worker forever
REQUEST_TIMEOUT = 60  # seconds
BODY_PREVIEW_LENGTH = 200


class BaseSource(object):
    # source code of the provider, first word of every error message
    name = None

    def get_data(self):
        pass

    def download(self, url: str, station: str, **kwargs) -> requests.Response | None:
        """
        GET url for station and return the response, or None after logging why it failed.

        Failures are logged at ERROR level: the Sentry logging integration turns each one into an event.
        The provider name is part of the message template while the details are its arguments, so Sentry
        groups the events by provider and cause whatever the station.
        """
        host = urlsplit(url).netloc
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
        except requests.ConnectTimeout:
            logger.error(f"{self.name}: station %s not downloaded: %s unreachable, no connection within %s s",
                         station, host, REQUEST_TIMEOUT)
            return None
        except requests.ReadTimeout:
            logger.error(f"{self.name}: station %s not downloaded: %s accepted the connection but sent no data "
                         "within %s s", station, host, REQUEST_TIMEOUT)
            return None
        except requests.RequestException as e:
            logger.error(f"{self.name}: station %s not downloaded: %s unreachable (%s)",
                         station, host, self.get_network_cause(e))
            return None

        if r.status_code != 200:
            logger.error(f"{self.name}: station %s not downloaded: %s answered HTTP %s, body: %r",
                         station, host, r.status_code, r.text[:BODY_PREVIEW_LENGTH])
            return None
        if not r.content.strip():
            logger.error(f"{self.name}: station %s not downloaded: %s answered HTTP 200 with an empty body",
                         station, host)
            return None
        return r

    def report_invalid_body(self, station: str, response: requests.Response, expected: str) -> None:
        """Log a response that arrived with HTTP 200 but cannot be parsed as expected."""
        logger.error(f"{self.name}: station %s not downloaded: %s answered HTTP 200 with a body that is not %s, "
                     "body: %r", station, urlsplit(response.url).netloc, expected, response.text[:BODY_PREVIEW_LENGTH])

    @staticmethod
    def get_network_cause(error: requests.RequestException) -> str:
        """
        Readable cause of a network error, e.g. "[Errno 111] Connection refused".

        The message of the exception is not used because it contains the URL, which for some providers
        carries the credentials in the query string.
        """
        reason = getattr(error.args[0], "reason", None) if error.args else None
        if reason is None:
            return type(error).__name__
        # urllib3 prefixes the reason with the repr of the connection object
        return str(reason).split(">: ", 1)[-1]
