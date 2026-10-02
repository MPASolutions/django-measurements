from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, router

from measurements.models import Measure


class Command(BaseCommand):
    """VACUUM ANALYZE of the compressed chunks of the measures whose uncompressed table still counts rows.

    Compressing a chunk leaves its rows dead in the uncompressed table, and autovacuum cleans them only if
    the statistics counted them. After a restart of Postgres the counters are gone, the dead rows stay, and
    the planner keeps trusting the old row count: every query over those weeks pays seconds of planning
    (5 s per weather query of the DSS on measurements, October 2026). A chunk already cleaned has no rows
    left in the statistics and is skipped, so a night with nothing to do lasts a few seconds.
    """

    help = "VACUUM ANALYZE of the compressed chunks of the measures with rows left in the uncompressed table"

    def handle(self, *args, **options) -> None:
        """Vacuum the chunks one at a time: an error on one is reported and the others still run."""
        connection = connections[router.db_for_write(Measure) or DEFAULT_DB_ALIAS]
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.chunk_schema, c.chunk_name
                FROM timescaledb_information.chunks c
                JOIN pg_class p ON p.oid = format('%%I.%%I', c.chunk_schema, c.chunk_name)::regclass
                WHERE c.hypertable_name = %s AND c.is_compressed AND p.reltuples > 0
                ORDER BY c.range_start
                """,
                [Measure._meta.db_table],
            )
            chunks = cursor.fetchall()

            cleaned = 0
            for schema, name in chunks:
                table = f"{connection.ops.quote_name(schema)}.{connection.ops.quote_name(name)}"
                try:
                    # PARALLEL 0: the parallel vacuum of the indexes needs shared memory that a container
                    # with the default 64 MB of /dev/shm does not have
                    cursor.execute(f"VACUUM (ANALYZE, PARALLEL 0) {table}")
                except DatabaseError as e:
                    self.stderr.write(f"{table}: {e}")
                    continue
                cleaned += 1

        self.stdout.write(f"Compressed chunks cleaned: {cleaned} of {len(chunks)}")
