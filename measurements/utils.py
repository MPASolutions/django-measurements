from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# from psqlextra.query import ConflictAction
from django.db import DEFAULT_DB_ALIAS, connections, router
from django.utils import timezone
from measurements.models import Measure, Station, Parameter, Sensor, Serie, Location
from measurements.quality import SerieQualityControl
import colorbrewer

# Columns touched by the load_serie() upsert below. The WHERE clause that
# skips no-op rewrites is derived from _MEASURE_UPDATE_COLUMNS, so a column
# added to what gets updated is automatically covered by the "did it
# actually change" check instead of silently bypassing it.
_MEASURE_CONFLICT_COLUMNS = ("serie_id", "timestamp")
_MEASURE_UPDATE_COLUMNS = ("serie_id", "timestamp", "value")


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


def load_serie(data, serie_id: int) -> bool:
    df = pd.DataFrame(data)
    df.dropna(inplace=True)
    # check for empty series
    if df.shape[0] == 0:
        return False
    df.reset_index(inplace=True)
    df.columns = ['timestamp', 'value']
    df['serie_id'] = serie_id

    # values no sensor can report are never written, and removed if an earlier load wrote them
    # while it could not judge them yet (a spike on the last sample has no neighbour after it)
    quality_control = SerieQualityControl.get_for_serie(serie_id)
    if quality_control is not None:
        flags = quality_control.get_flags(df['timestamp'], df['value'])
        quality_control.log_flags(serie_id, df['timestamp'], flags)
        failed = flags == quality_control.FAIL
        if failed.any():
            Measure.objects.filter(serie_id=serie_id, timestamp__in=list(df.loc[failed, 'timestamp'])).delete()
            df = df[~failed]
        if df.shape[0] == 0:
            return False

    _upsert_measures(df.to_dict(orient='records'))

    return True


def _upsert_measures(rows: list[dict[str, object]]) -> None:
    """
    Upsert rows into Measure, touching a stored row only when it actually changed.

    Providers are downloaded again over windows already loaded, so most of the rows offered here
    are already stored and identical. Two costs follow, and each has its own remedy.

    Django's bulk_create(update_conflicts=True) builds an INSERT ... ON CONFLICT DO UPDATE with no
    way to add a WHERE, so every conflicting row is rewritten even when nothing changed, which on
    the measures hypertable defeats HOT updates and keeps rewriting the UNIQUE index and both GIN
    indexes. The statement is therefore written by hand with WHERE ... IS DISTINCT FROM EXCLUDED. ...
    on every column the upsert updates (not just value), so a real change on any of them still
    writes. IS DISTINCT FROM is used instead of <> because it treats NULL correctly.

    Even with that WHERE, a row that reaches ON CONFLICT is locked first, and the lock is written to
    the WAL: on PostgreSQL 15 an upsert of 50,000 identical rows writes no tuple but about 6 MB of
    WAL. The offered rows are therefore compared with the stored ones in the same statement, and
    only the new or different ones go on to the INSERT. The stored rows are read through a
    subquery bounded on the series and on the time span of the batch, with constants, so
    TimescaleDB excludes the other chunks when it plans the query. ON CONFLICT stays: two loads of
    the same window can still run together, and the second one must not fail on the key.

    The comparison is exact on purpose: values reach here already parsed to the same float64 the
    column stores, so an identical reading re-sent by the same provider is bit-for-bit identical,
    while a tolerance would risk silently swallowing a real correction the provider sends for the
    same timestamp.

    Field values go through Field.get_db_prep_save(), the same documented extension point Django's
    own bulk_create relies on, so this does not have to reimplement type adaptation (timezone
    handling included); each placeholder is cast to the type of its column, because a VALUES list
    read by a SELECT has no target column to take the type from.
    """
    if not rows:
        return

    db_alias = router.db_for_write(Measure) or DEFAULT_DB_ALIAS
    connection = connections[db_alias]
    fields = {name: Measure._meta.get_field(name) for name in _MEASURE_UPDATE_COLUMNS}

    def quoted(name: str) -> str:
        return connection.ops.quote_name(fields[name].column)

    def prepared(name: str, value: object) -> object:
        """Adapt a value to its column, as bulk_create would."""
        return fields[name].get_db_prep_save(value, connection=connection)

    table = connection.ops.quote_name(Measure._meta.db_table)
    columns_sql = ", ".join(quoted(name) for name in _MEASURE_UPDATE_COLUMNS)
    conflict_sql = ", ".join(quoted(name) for name in _MEASURE_CONFLICT_COLUMNS)
    set_sql = ", ".join(f"{quoted(name)} = EXCLUDED.{quoted(name)}" for name in _MEASURE_UPDATE_COLUMNS)
    changed_sql = " OR ".join(
        f"{table}.{quoted(name)} IS DISTINCT FROM EXCLUDED.{quoted(name)}" for name in _MEASURE_UPDATE_COLUMNS
    )
    joined_sql = " AND ".join(f"stored.{quoted(name)} = offered.{quoted(name)}" for name in _MEASURE_CONFLICT_COLUMNS)
    different_sql = " OR ".join(
        f"stored.{quoted(name)} IS DISTINCT FROM offered.{quoted(name)}"
        for name in _MEASURE_UPDATE_COLUMNS
        if name not in _MEASURE_CONFLICT_COLUMNS
    )
    row_placeholder = "({})".format(
        ", ".join(f"CAST(%s AS {fields[name].db_type(connection)})" for name in _MEASURE_UPDATE_COLUMNS)
    )

    params = []
    for row in rows:
        params.extend(prepared(name, row[name]) for name in _MEASURE_UPDATE_COLUMNS)

    serie_ids = sorted({row["serie_id"] for row in rows})
    params.extend(prepared("serie_id", serie_id) for serie_id in serie_ids)
    for bound in (min(row["timestamp"] for row in rows), max(row["timestamp"] for row in rows)):
        # with USE_TZ = False the bound is naive, and PostgreSQL casts a naive value to timestamptz
        # by the session time zone, a cast it deems only stable: TimescaleDB then cannot exclude
        # chunks when it plans the query and reads them all (measured: 40 out of 40 for a batch
        # spanning 2). Given the zone the session would use, the value is the same and becomes a
        # constant the planner can exclude chunks with
        if isinstance(bound, datetime) and timezone.is_naive(bound):
            bound = timezone.make_aware(bound, connection.timezone)
        params.append(prepared("timestamp", bound))

    sql = (
        f"INSERT INTO {table} ({columns_sql}) "
        f"SELECT {', '.join(f'offered.{quoted(name)}' for name in _MEASURE_UPDATE_COLUMNS)} "
        f"FROM (VALUES {', '.join([row_placeholder] * len(rows))}) AS offered ({columns_sql}) "
        f"LEFT JOIN (SELECT {columns_sql} FROM {table} "
        f"WHERE {quoted('serie_id')} IN ({', '.join(['%s'] * len(serie_ids))}) "
        f"AND {quoted('timestamp')} BETWEEN %s AND %s) AS stored ON {joined_sql} "
        f"WHERE stored.{quoted('serie_id')} IS NULL OR {different_sql} "
        f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {set_sql} WHERE {changed_sql}"
    )

    with connection.cursor() as cursor:
        cursor.execute(sql, params)


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
