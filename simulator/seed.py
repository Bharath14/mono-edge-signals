"""Seed mode: generate the 10 minute loop and load it through the pipeline.

Usage
-----
    python -m simulator.seed                 # seed the database in DATABASE_URL
    python -m simulator.seed --reset         # wipe the tables first
    python -m simulator.seed --no-faults     # clean data only

Running it twice is safe: every insert is idempotent.
"""

import argparse
import logging
import pathlib
import time
from datetime import timedelta

import psycopg

from . import config as c
from . import generator
from .pipeline import Ingestor
from .rollup import rollup_range
from detector.store import detect_range

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def apply_schema(dsn):
    with psycopg.connect(dsn) as conn:
        conn.execute(SCHEMA_PATH.read_text())


def reset_tables(dsn):
    """Drop the data (including processed partitions), keep the schema."""
    with psycopg.connect(dsn) as conn:
        parts = conn.execute(
            "SELECT inhrelid::regclass::text FROM pg_inherits "
            "WHERE inhparent = 'processed_readings'::regclass"
        ).fetchall()
        for (name,) in parts:
            conn.execute(f"DROP TABLE {name}")
        conn.execute(
            "TRUNCATE raw_readings, historical_rollups, rejected_readings, "
            "incident_snapshots, incidents RESTART IDENTITY CASCADE"
        )


def summarize(dsn):
    queries = {
        "raw_readings": "SELECT count(*) FROM raw_readings",
        "processed_readings": "SELECT count(*) FROM processed_readings",
        "historical_rollups": "SELECT count(*) FROM historical_rollups",
        "rejected_readings": "SELECT count(*) FROM rejected_readings",
        "incidents": "SELECT count(*) FROM incidents",
        "incident_snapshots": "SELECT count(*) FROM incident_snapshots",
    }
    out = {}
    with psycopg.connect(dsn) as conn:
        for name, sql in queries.items():
            out[name] = conn.execute(sql).fetchone()[0]
        out["reject_reasons"] = dict(
            conn.execute(
                "SELECT split_part(reason, ':', 1), count(*) FROM rejected_readings "
                "GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
        )
        sizes = {
            name: conn.execute("SELECT pg_total_relation_size(%s::regclass)", (name,)).fetchone()[0]
            for name in ("raw_readings", "historical_rollups", "incident_snapshots")
        }
        # A partitioned parent reports 0 bytes, so add up its partitions.
        sizes["processed_readings"] = conn.execute(
            "SELECT coalesce(sum(pg_total_relation_size(inhrelid)), 0) FROM pg_inherits "
            "WHERE inhparent = 'processed_readings'::regclass"
        ).fetchone()[0]
        out["size_mb"] = {name: round(int(v) / 1e6, 2) for name, v in sizes.items()}
    return out


def seed(dsn, batch_size=500, faults=True, reset=False, spool_path="spool/pending_batches.jsonl"):
    apply_schema(dsn)
    if reset:
        reset_tables(dsn)

    data = generator.generate_loop()
    messages = generator.build_messages(data)
    fault_counts = {}
    if faults:
        messages, fault_counts = generator.inject_faults(messages)

    ingestor = Ingestor(dsn, spool_path=spool_path)
    started = time.time()
    for i in range(0, len(messages), batch_size):
        ingestor.ingest(messages[i : i + batch_size])
    replayed = ingestor.flush_spool()

    with psycopg.connect(dsn) as conn:
        end = c.LOOP_START + timedelta(seconds=c.LOOP_SECONDS)
        buckets = rollup_range(conn, c.MILL_ID, c.LOOP_START, end)
        incidents = detect_range(conn, c.MILL_ID, c.LOOP_START, end)
    ingestor.close()

    return {
        "messages_sent": len(messages),
        "faults_injected": fault_counts,
        "inserted_this_run": vars(ingestor.totals),
        "spooled_batches": ingestor.spooled_batches,
        "replayed_from_spool": replayed,
        "rollup_buckets": buckets,
        "incidents": len(incidents),
        "seconds": round(time.time() - started, 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--dsn", default=c.DATABASE_URL)
    parser.add_argument("--reset", action="store_true", help="wipe tables before seeding")
    parser.add_argument("--no-faults", action="store_true", help="do not inject data faults")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = seed(args.dsn, args.batch_size, faults=not args.no_faults, reset=args.reset)
    print("Seed run:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print("Database now holds:")
    for key, value in summarize(args.dsn).items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
