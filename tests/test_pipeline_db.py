"""Integration tests. They need a real Postgres.

    TEST_DATABASE_URL=postgresql://mill:mill@localhost:5432/millsignals pytest

They wipe the tables in that database, so point them at a scratch database.
"""

import json
import os
from datetime import timedelta

import psycopg
import pytest

from simulator import config as c
from simulator.pipeline import Ingestor
from simulator.seed import apply_schema, seed

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set TEST_DATABASE_URL to run DB tests")


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    spool = str(tmp_path_factory.mktemp("spool") / "pending.jsonl")
    first = seed(DSN, reset=True, spool_path=spool)
    return first


def test_seed_loads_every_layer(seeded):
    f = seeded["faults_injected"]
    sent = 30_000 - f["dropped_tick"]
    assert seeded["messages_sent"] == sent
    with psycopg.connect(DSN) as conn:
        assert count(conn, "raw_readings") == sent               # nothing refused
        # whole-message rejects (bad timestamp) never reach processed
        assert count(conn, "processed_readings") == sent - f["bad_timestamp"]
        assert count(conn, "rejected_readings") > 0
        assert count(conn, "historical_rollups") > 590


def test_rejects_have_reasons_for_each_injected_fault(seeded):
    f = seeded["faults_injected"]
    with psycopg.connect(DSN) as conn:
        rows = dict(
            conn.execute(
                "SELECT split_part(reason, ':', 1), count(*) FROM rejected_readings GROUP BY 1"
            ).fetchall()
        )
    assert rows["bad_timestamp"] == f["bad_timestamp"]
    assert rows["out_of_range"] == f["sentinel_value"]
    assert "non_numeric" not in rows  # numeric strings are converted, not rejected


def test_processed_is_partitioned_by_hour(seeded):
    with psycopg.connect(DSN) as conn:
        parts = conn.execute(
            "SELECT inhrelid::regclass::text FROM pg_inherits "
            "WHERE inhparent = 'processed_readings'::regclass"
        ).fetchall()
    assert [p[0] for p in parts] == ["processed_readings_2026010100"]


def test_raw_keeps_malformed_messages_exactly(seeded):
    with psycopg.connect(DSN) as conn:
        row = conn.execute(
            "SELECT payload FROM raw_readings WHERE ts_text = 'not-a-timestamp' LIMIT 1"
        ).fetchone()
    assert row is not None and row[0]["timestamp"] == "not-a-timestamp"


def test_rerunning_the_seed_adds_nothing(seeded, tmp_path):
    with psycopg.connect(DSN) as conn:
        before = {t: count(conn, t) for t in ("raw_readings", "processed_readings", "rejected_readings", "historical_rollups")}
    again = seed(DSN, spool_path=str(tmp_path / "pending.jsonl"))
    with psycopg.connect(DSN) as conn:
        after = {t: count(conn, t) for t in before}
    assert before == after
    assert again["inserted_this_run"]["raw_inserted"] == 0
    assert again["inserted_this_run"]["processed_inserted"] == 0


def test_rollup_keeps_the_cobble_spike_in_max(seeded):
    start = c.LOOP_START + timedelta(seconds=30)
    with psycopg.connect(DSN) as conn:
        vib_max, vib_avg, speed_min = conn.execute(
            "SELECT max(vib_max), max(vib_avg), min(speed_min) FROM historical_rollups "
            "WHERE bucket_ts >= %s AND bucket_ts < %s",
            (start, start + timedelta(seconds=10)),
        ).fetchone()
    assert vib_max > 6.0 and vib_max > vib_avg
    assert speed_min < 500


def test_rollup_rows_are_consistent_with_processed(seeded):
    with psycopg.connect(DSN) as conn:
        bad = conn.execute(
            "SELECT count(*) FROM historical_rollups "
            "WHERE speed_min > speed_avg OR speed_avg > speed_max OR sample_count < 1 OR sample_count > 50"
        ).fetchone()[0]
        total = conn.execute("SELECT sum(sample_count) FROM historical_rollups").fetchone()[0]
        processed = count(conn, "processed_readings")
    assert bad == 0
    assert total == processed


def test_unreachable_database_spools_then_replays(tmp_path):
    apply_schema(DSN)
    with psycopg.connect(DSN) as conn:
        conn.execute("DELETE FROM raw_readings WHERE mill_id = 'RM-SPOOL'")
        conn.execute("DELETE FROM processed_readings WHERE mill_id = 'RM-SPOOL'")
        conn.commit()

    batch = [
        {
            "mill_id": "RM-SPOOL",
            "timestamp": f"2026-01-01T00:00:00.{i * 20:03d}Z",
            "motor_speed": 1000.0, "motor_current": 150.0, "torque": 40.0,
            "rolling_force": 2000.0, "vibration": 2.0, "temperature": 75.0,
        }
        for i in range(5)
    ]
    spool = str(tmp_path / "pending.jsonl")
    sleeps = []
    broken = Ingestor(
        "postgresql://nobody:x@127.0.0.1:1/none",
        spool_path=spool, max_retries=2, base_delay=0.5, sleep=sleeps.append,
    )
    assert broken.ingest(batch) is False
    assert sleeps == [0.5, 1.0]                   # exponential backoff
    assert len(open(spool).read().splitlines()) == 1

    good = Ingestor(DSN, spool_path=spool)
    assert good.flush_spool() == 1
    assert not os.path.exists(spool)
    # replaying the same spool again must not duplicate anything
    with open(spool, "w") as fh:
        fh.write(json.dumps(batch) + "\n")
    assert good.flush_spool() == 1
    with psycopg.connect(DSN) as conn:
        assert conn.execute("SELECT count(*) FROM processed_readings WHERE mill_id = 'RM-SPOOL'").fetchone()[0] == 5
    good.close()


def test_seed_stores_one_incident_per_cobble(seeded):
    assert seeded["incidents"] == 10
    with psycopg.connect(DSN) as conn:
        rows = conn.execute(
            "SELECT started_at, ended_at, affected_signals, reason, peak_values "
            "FROM incidents ORDER BY started_at"
        ).fetchall()
    assert len(rows) == 10
    for (started, ended, signals, reason, peaks), cob_s in zip(rows, c.COBBLE_STARTS_S):
        offset = (started - c.LOOP_START).total_seconds()
        assert cob_s <= offset < cob_s + 0.5
        assert ended is not None and ended > started
        assert "motor_speed" in signals and "vibration" in signals
        assert reason.startswith("Cobble pattern")
        assert peaks["max_vibration"] > 6.0


def test_incident_snapshots_cover_thirty_seconds_each_side(seeded):
    with psycopg.connect(DSN) as conn:
        rows = conn.execute(
            "SELECT i.started_at, i.ended_at, min(s.ts), max(s.ts), count(*) "
            "FROM incidents i JOIN incident_snapshots s ON s.incident_id = i.id "
            "GROUP BY i.id ORDER BY i.started_at"
        ).fetchall()
    assert len(rows) == 10
    # middle incidents have data on both sides; the window is about 30 s + duration + 30 s
    started, ended, first, last, n = rows[1]
    assert (started - first).total_seconds() == pytest.approx(30, abs=0.1)
    assert (last - ended).total_seconds() == pytest.approx(30, abs=0.1)
    assert n > 50 * 60


def test_rerunning_detection_does_not_duplicate(seeded):
    from detector.store import detect_range

    end = c.LOOP_START + timedelta(seconds=c.LOOP_SECONDS)
    with psycopg.connect(DSN) as conn:
        before = (count(conn, "incidents"), count(conn, "incident_snapshots"))
        detect_range(conn, c.MILL_ID, c.LOOP_START, end)
        after = (count(conn, "incidents"), count(conn, "incident_snapshots"))
    assert before == after
