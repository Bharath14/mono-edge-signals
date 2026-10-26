"""Run the cobble detector over stored data and save incidents.

Usage
-----
    python -m detector.store                          # the seeded 10 minute loop
    python -m detector.store --from 2026-01-01T00:00:00Z --to 2026-01-01T01:00:00Z

Re-running over the same range is safe: incidents are upserted on
(mill_id, started_at) and their snapshots are rebuilt.
"""

import argparse
from datetime import datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from simulator import config as c
from .cobble import BASELINE_S, detect

SNAPSHOT_PAD = timedelta(seconds=30)

READ_SQL = """
SELECT ts, motor_speed, motor_current, torque, rolling_force, vibration, temperature
FROM processed_readings
WHERE mill_id = %s AND ts >= %s AND ts < %s
ORDER BY ts
"""

UPSERT_SQL = """
INSERT INTO incidents (mill_id, started_at, ended_at, affected_signals, reason, peak_values)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (mill_id, started_at) DO UPDATE SET
  ended_at = EXCLUDED.ended_at,
  affected_signals = EXCLUDED.affected_signals,
  reason = EXCLUDED.reason,
  peak_values = EXCLUDED.peak_values
RETURNING id
"""

# Full resolution rows around the incident, copied so the incident view still
# works after the processed partition has been dropped by retention.
SNAPSHOT_SQL = """
INSERT INTO incident_snapshots
  (incident_id, mill_id, ts, motor_speed, motor_current, torque, rolling_force, vibration, temperature)
SELECT %s, mill_id, ts, motor_speed, motor_current, torque, rolling_force, vibration, temperature
FROM processed_readings
WHERE mill_id = %s AND ts >= %s AND ts < %s
"""


def save_incident(cur, mill_id, record):
    cur.execute(
        UPSERT_SQL,
        (
            mill_id,
            record["started_at"],
            record["ended_at"],
            record["affected_signals"],
            record["reason"],
            Jsonb(record["peak_values"]),
        ),
    )
    incident_id = cur.fetchone()[0]
    end = record["ended_at"] or record["started_at"]
    cur.execute("DELETE FROM incident_snapshots WHERE incident_id = %s", (incident_id,))
    cur.execute(
        SNAPSHOT_SQL,
        (incident_id, mill_id, record["started_at"] - SNAPSHOT_PAD, end + SNAPSHOT_PAD),
    )
    return incident_id


def detect_range(conn, mill_id, start, end):
    """Detect incidents starting in [start, end) and store them.

    Reads a little earlier than `start` so the baseline is warm at `start`.
    Returns the stored records.
    """
    warm_from = start - timedelta(seconds=BASELINE_S)
    with conn.cursor() as cur:
        rows = cur.execute(READ_SQL, (mill_id, warm_from, end)).fetchall()
    closed, still_open = detect(rows)
    found = closed + ([still_open] if still_open else [])
    records = [inc.as_record() for inc in found if inc.started_at >= start]
    with conn.transaction():
        with conn.cursor() as cur:
            for rec in records:
                save_incident(cur, mill_id, rec)
    return records


def _parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--dsn", default=c.DATABASE_URL)
    parser.add_argument("--mill", default=c.MILL_ID)
    parser.add_argument("--from", dest="start", type=_parse, default=c.LOOP_START)
    parser.add_argument(
        "--to", dest="end", type=_parse,
        default=c.LOOP_START + timedelta(seconds=c.LOOP_SECONDS),
    )
    args = parser.parse_args()
    with psycopg.connect(args.dsn) as conn:
        records = detect_range(conn, args.mill, args.start, args.end)
    print(f"{len(records)} incidents stored")
    for r in records:
        print(f"  {r['started_at'].isoformat()}  {r['reason']}")


if __name__ == "__main__":
    main()
