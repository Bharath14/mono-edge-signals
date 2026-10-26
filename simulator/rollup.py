"""1 second rollups (min, avg, max per signal) built from processed_readings.

Min and max are kept on purpose: a cobble's vibration spike lasts a moment and
an average alone would smooth it away. The statement is an upsert, so running
it twice for the same range is safe.
"""

from . import config as c


def _build_sql():
    select_cols, update_cols, insert_cols = [], [], []
    for sig in c.SIGNALS:
        p = c.ROLLUP_PREFIX[sig]
        for fn in ("avg", "min", "max"):
            insert_cols.append(f"{p}_{fn}")
            select_cols.append(f"{fn}({sig})")
            update_cols.append(f"{p}_{fn} = EXCLUDED.{p}_{fn}")
    return f"""
INSERT INTO historical_rollups (mill_id, bucket_ts, {", ".join(insert_cols)}, sample_count)
SELECT mill_id, date_trunc('second', ts) AS bucket_ts,
       {", ".join(select_cols)}, count(*)
FROM processed_readings
WHERE mill_id = %s AND ts >= %s AND ts < %s
GROUP BY mill_id, date_trunc('second', ts)
ON CONFLICT (mill_id, bucket_ts) DO UPDATE SET
       {", ".join(update_cols)}, sample_count = EXCLUDED.sample_count
"""


ROLLUP_SQL = _build_sql()


def rollup_range(conn, mill_id, start, end):
    """Aggregate processed rows in [start, end) into 1 second buckets."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(ROLLUP_SQL, (mill_id, start, end))
            return cur.rowcount
