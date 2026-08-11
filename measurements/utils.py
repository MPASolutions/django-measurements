from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

from django.conf import settings
from django.utils import timezone as django_timezone

# from psqlextra.query import ConflictAction
from measurements.models import Measure, Station, Parameter, Sensor, Serie, Location
import colorbrewer

# A station is judged against the cadence of its own data instead of a fixed age: the networks loaded
# here range from five minute loggers to hourly regional services, so a single threshold would be
# blind on the fast ones and noisy on the slow ones. The cadence is the median gap between the
# timestamps just loaded, and this many consecutive missing samples make the station stale.
MISSED_SAMPLES_BEFORE_STALE = 3

# Used only when one sample was loaded, so there is no gap to measure a cadence on.
CADENCE_FALLBACK_SECONDS = 3600.0


def get_serie(station, parameter, sensor='unknown', height=None, location=None):
    if not isinstance(station, Station):
        station, created = Station.objects.get_or_create(code=station)
    if not isinstance(parameter, Parameter):
        parameter, created = Parameter.objects.get_or_create(code=parameter)
    if not isinstance(sensor, Sensor):
        sensor, created = Sensor.objects.get_or_create(code=sensor)
    # try to use Station.location when location is not specified
    if location is None:
        location = station.location
    else:
        if not isinstance(location, Location):
            location, created = Location.objects.get_or_create(label=location)

    serie, created = Serie.objects.get_or_create(station=station,
                                                 parameter=parameter,
                                                 sensor=sensor,
                                                 height=height,
                                                 location=location)
    return serie


def reference_now():
    """
    Current time on the same clock as the timestamps read back from the database.

    With ``USE_TZ = False`` the ORM hands back naive datetimes already converted to
    ``settings.TIME_ZONE`` by the database session, while ``datetime.now()`` follows the time zone
    of the process. The containers of this project run on UTC and ``TIME_ZONE`` is Europe/Rome, so
    the two clocks sat two hours apart and every freshness check silently tolerated its limit plus
    the UTC offset. Read the current time from here and the two sides of the comparison agree.
    """

    if getattr(settings, 'USE_TZ', False):
        return django_timezone.now()

    return datetime.now(ZoneInfo(settings.TIME_ZONE)).replace(tzinfo=None)


def to_reference_clock(value):
    """Express a timestamp on the same clock as :func:`reference_now`, whatever it carries."""

    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()

    is_aware = value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None
    if getattr(settings, 'USE_TZ', False):
        return value if is_aware else value.replace(tzinfo=ZoneInfo(settings.TIME_ZONE))
    if is_aware:
        return value.astimezone(ZoneInfo(settings.TIME_ZONE)).replace(tzinfo=None)

    return value


def format_duration(seconds):
    """Turn a number of seconds into something a human reads without doing arithmetic."""

    if seconds is None:
        return 'n/a'

    total = int(abs(seconds))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return '{}d {}h {}m'.format(days, hours, minutes)
    if hours:
        return '{}h {}m'.format(hours, minutes)
    if minutes:
        return '{}m {}s'.format(minutes, secs)

    return '{}s'.format(secs)


def format_timestamp(value):
    return 'never' if value is None else value.strftime('%Y-%m-%d %H:%M:%S')


def stale_after_seconds(cadence_seconds):
    """How old data of this cadence may get before the source is considered silent."""

    return (cadence_seconds or CADENCE_FALLBACK_SECONDS) * MISSED_SAMPLES_BEFORE_STALE


def load_age_seconds(last_timestamp):
    """Age of the newest sample loaded, negative for forecasts, None when nothing was loaded."""

    if last_timestamp is None:
        return None

    return (reference_now() - last_timestamp).total_seconds()


def is_load_stale(last_timestamp, cadence_seconds):
    age = load_age_seconds(last_timestamp)

    return age is not None and age > stale_after_seconds(cadence_seconds)


def describe_load(rows, last_timestamp, cadence_seconds):
    """One line stating what was written and how recent it is, ready for stdout."""

    if not rows:
        return '[FAILED] no usable data returned by the provider'

    age = load_age_seconds(last_timestamp)
    latest = format_timestamp(last_timestamp)
    cadence = 'cadence {}'.format(format_duration(cadence_seconds)) if cadence_seconds else 'cadence n/a'
    if age is None:
        return '[OK] {} rows, no timestamp to judge freshness on'.format(rows)
    if age < 0:
        # forecast sources legitimately write into the future: report the horizon, not an age
        return '[OK] {} rows, reaching {} ({} ahead, {})'.format(rows, latest, format_duration(age), cadence)
    if age > stale_after_seconds(cadence_seconds):
        return '[STALE] {} rows, latest {} ({} ago, {}, expected within {})'.format(
            rows, latest, format_duration(age), cadence, format_duration(stale_after_seconds(cadence_seconds))
        )

    return '[OK] {} rows, latest {} ({} ago, {})'.format(rows, latest, format_duration(age), cadence)


def write_load_outcome(command, outcome, ending='\n'):
    """
    Print the outcome of a load on a management command, styled by what actually happened.

    Green for fresh data, yellow for data that arrived but is older than the source cadence, red for
    nothing usable. The distinction is the whole point: a station whose provider keeps serving the
    same old samples used to be printed in green like every other one.
    """

    if not outcome.rows:
        style = command.style.ERROR
    elif outcome.is_stale:
        style = command.style.WARNING
    else:
        style = command.style.SUCCESS

    command.stdout.write(style(outcome.describe()), ending=ending)


@dataclass(frozen=True)
class SerieLoadResult:
    """
    What one call to :func:`load_serie` actually wrote.

    The boolean protocol is kept because every caller used to read the return value as a flag. The
    extra fields are what lets a command tell "the provider answered" from "the provider answered
    with fresh data": a row count alone cannot, and a provider that keeps serving yesterday's
    samples looks identical to a healthy one.
    """

    rows: int
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    cadence_seconds: float | None = None

    def __bool__(self) -> bool:
        return self.rows > 0

    @property
    def age_seconds(self):
        return load_age_seconds(self.last_timestamp)

    @property
    def is_stale(self):
        return is_load_stale(self.last_timestamp, self.cadence_seconds)

    def describe(self):
        return describe_load(self.rows, self.last_timestamp, self.cadence_seconds)


class StationLoadReport:
    """
    Outcome of loading every serie of one station, judged against the cadence of the data itself.

    Commands feed it the result of each :func:`load_serie` call and print :meth:`describe` in place
    of a bare ``[OK]``, so the worker log says how recent the data is and not only that some rows
    were written.
    """

    def __init__(self, label=None):
        self.label = label
        self.results = []

    def add(self, result):
        """Accept a :class:`SerieLoadResult`, or the plain boolean older callers may still pass."""

        if isinstance(result, SerieLoadResult):
            self.results.append(result)

    @property
    def rows(self):
        return sum(result.rows for result in self.results)

    @property
    def last_timestamp(self):
        stamps = [result.last_timestamp for result in self.results if result.last_timestamp is not None]

        return max(stamps) if stamps else None

    @property
    def cadence_seconds(self):
        """Fastest cadence among the series of the station: the one that goes stale first."""

        cadences = [result.cadence_seconds for result in self.results if result.cadence_seconds]

        return min(cadences) if cadences else None

    @property
    def age_seconds(self):
        return load_age_seconds(self.last_timestamp)

    @property
    def is_stale(self):
        return is_load_stale(self.last_timestamp, self.cadence_seconds)

    def describe(self):
        return describe_load(self.rows, self.last_timestamp, self.cadence_seconds)


def _measure_cadence(timestamps):
    """Median gap between consecutive samples, in seconds, or None when there is nothing to measure."""

    # a few callers build the frame from something other than a time index, and a non temporal
    # column would turn the gaps into plain numbers instead of durations
    if not pd.api.types.is_datetime64_any_dtype(timestamps) or len(timestamps) < 2:
        return None

    gaps = timestamps.sort_values().diff().dropna()
    if gaps.empty:
        return None

    cadence = gaps.median().total_seconds()

    return cadence or None


def load_serie(data, serie_id):
    df = pd.DataFrame(data)
    df.dropna(inplace=True)
    # check for empty series
    if df.shape[0] == 0:
        return SerieLoadResult(rows=0)
    df.reset_index(inplace=True)
    df.columns = ['timestamp', 'value']
    df['serie_id'] = serie_id
    conflict_columns = ['serie_id', 'timestamp']

    datadict = df.to_dict(orient='records')

    # Measure.extra.on_conflict(conflict_columns,
    #                           ConflictAction.UPDATE).bulk_insert(datadict)

    Measure.objects.bulk_create(
        [Measure(**row) for row in datadict],
        update_conflicts=True,
        unique_fields=conflict_columns,
        update_fields=["serie_id", "value", "timestamp"],
    )

    is_temporal = pd.api.types.is_datetime64_any_dtype(df['timestamp'])

    return SerieLoadResult(
        rows=df.shape[0],
        first_timestamp=to_reference_clock(df['timestamp'].min()) if is_temporal else None,
        last_timestamp=to_reference_clock(df['timestamp'].max()) if is_temporal else None,
        cadence_seconds=_measure_cadence(df['timestamp']),
    )


def strong_float(value):
    if value in [None, '']:
        return None
    else:
        return float(value)


def get_time(time):
    now = datetime.now()
    if time == "last":
        start_time = now - timedelta(hours=1)
        end_time = now
    elif time == 'today':
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = now.replace(hour=23, minute=59, second=59, microsecond=0)
    elif time == 'yesterday':
        yesterday = now - timedelta(days=1)
        start_time = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = yesterday.replace(hour=23, minute=59, second=59, microsecond=0)
    elif time == '12h':
        start_time = now - timedelta(hours=12)
        end_time = now
    elif time == '24h':
        start_time = now - timedelta(hours=24)
        end_time = now
    elif time == '36h':
        start_time = now - timedelta(hours=36)
        end_time = now
    elif time == '48h':
        start_time = now - timedelta(hours=48)
        end_time = now
    elif time == '72h':
        start_time = now - timedelta(hours=72)
        end_time = now
    elif time == 'week':
        start_time = now - timedelta(weeks=1)
        end_time = now
    elif time == '30g':
        start_time = now - timedelta(days=30)
        end_time = now

    return start_time, end_time


def get_bins(values_list, k=8, zeros=True):
    values = np.array(values_list)
    if not zeros:
        _values = values[values != 0]
    else:
        _values = values
    #
    if _values[_values != 0].size == 0:
        _values = np.array([0, 1])
    counts, bins = np.histogram(_values, bins=k)
    return counts, bins


def classify_fc(fc, k=8, zeros=True, cmap='Blues'):
    """Classify in place a FeatureCollection object.

    Arguments:
    fc -- FeatureCollection object
    k -- number of classes
    """
    items = fc['features']
    values_list = [float(i['properties']['value']) for i in items]

    counts, bins = get_bins(values_list, k, zeros)
    # classes = Equal_Interval(_values, k)

    # cmap = get_cmap(cmap, k)
    cmap = getattr(colorbrewer, cmap)[k]

    for i in items:
        value = float(i['properties']['value'])
        bin = np.fmin(np.digitize(value, bins), k)
        # color = cmap(_class)
        color = cmap[bin -1]
        i['properties']['class'] = str(bin -1)
        # i['properties']['color'] = int(color[0] * 255), int(color[1] * 255), int(color[2] * 255), color[3]
        i['properties']['color'] = color + (1.0,)
        i['properties']['color'] = [str(c) for c in i['properties']['color']]
        i['properties']['value'] = str(round(value, 2))
