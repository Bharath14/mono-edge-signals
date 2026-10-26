"""Ingestion pipeline: raw -> clean -> processed, in one transaction per batch.

Failure handling
----------------
* Retried batch / re-run seed   idempotent inserts (ON CONFLICT DO NOTHING)
* Database slow or briefly down retry with exponential backoff
* Database down for longer      batch is appended to a local spool file and
                                replayed later with Ingestor.flush_spool()
* Malformed message             stored in raw, logged in rejected_readings
* Crash mid batch               the batch is one transaction, so it is either
                                fully stored or not stored at all
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import timedelta

import psycopg
from psycopg.types.json import Jsonb

from . import config as c
from .cleaning import clean_message

log = logging.getLogger("pipeline")

RAW_SQL = """
INSERT INTO raw_readings (mill_id, ts_text, payload)
VALUES (%s, %s, %s)
ON CONFLICT (mill_id, ts_text, payload_md5) DO NOTHING
"""

PROCESSED_SQL = """
INSERT INTO processed_readings
  (mill_id, ts, motor_speed, motor_current, torque, rolling_force, vibration, temperature)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (mill_id, ts) DO NOTHING
"""

REJECT_SQL = """
INSERT INTO rejected_readings (mill_id, ts_text, payload, reason)
VALUES (%s, %s, %s, %s)
ON CONFLICT (mill_id, ts_text, reason, payload_md5) DO NOTHING
"""


@dataclass
class BatchStats:
    received: int = 0
    raw_inserted: int = 0
    processed_inserted: int = 0
    rejects_logged: int = 0

    def add(self, other):
        self.received += other.received
        self.raw_inserted += other.raw_inserted
        self.processed_inserted += other.processed_inserted
        self.rejects_logged += other.rejects_logged


def _identity(msg):
    if isinstance(msg, dict):
        mill = msg.get("mill_id")
        ts = msg.get("timestamp")
        return (
            mill if isinstance(mill, str) else "",
            ts if isinstance(ts, str) else ("" if ts is None else str(ts)),
        )
    return "", ""


def partition_name(hour_start):
    return "processed_readings_" + hour_start.strftime("%Y%m%d%H")


def ensure_partitions(cur, timestamps):
    """Create the hourly partition for every hour present in `timestamps`."""
    hours = {ts.replace(minute=0, second=0, microsecond=0) for ts in timestamps}
    for hour in sorted(hours):
        nxt = hour + timedelta(hours=1)
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {partition_name(hour)} "
            f"PARTITION OF processed_readings "
            f"FOR VALUES FROM ('{hour.isoformat()}') TO ('{nxt.isoformat()}')"
        )


def process_batch(conn, batch):
    """Write one batch (list of messages) to raw, processed and rejects.

    Everything happens in a single transaction.
    """
    stats = BatchStats(received=len(batch))
    raw_rows, good_rows, reject_rows = [], [], []

    for msg in batch:
        mill, ts_text = _identity(msg)
        raw_rows.append((mill, ts_text, Jsonb(msg)))
        result = clean_message(msg)
        if result.row is not None:
            good_rows.append(result.row)
        for r in result.rejects:
            reject_rows.append((r["mill_id"], r["ts_text"], Jsonb(r["payload"]), r["reason"]))

    with conn.transaction():
        with conn.cursor() as cur:
            if good_rows:
                ensure_partitions(cur, [row[1] for row in good_rows])
            cur.executemany(RAW_SQL, raw_rows)
            stats.raw_inserted = cur.rowcount
            cur.executemany(PROCESSED_SQL, good_rows)
            stats.processed_inserted = cur.rowcount
            cur.executemany(REJECT_SQL, reject_rows)
            stats.rejects_logged = cur.rowcount
    return stats


class Ingestor:
    """Batch writer with retry, backoff and a local spool file."""

    def __init__(
        self,
        dsn=None,
        spool_path="spool/pending_batches.jsonl",
        max_retries=4,
        base_delay=0.5,
        sleep=time.sleep,
    ):
        self.dsn = dsn or c.DATABASE_URL
        self.spool_path = spool_path
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._sleep = sleep
        self._conn = None
        self.totals = BatchStats()
        self.spooled_batches = 0

    # -- connection ----------------------------------------------------------
    def _connection(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.dsn, connect_timeout=5)
        return self._conn

    def close(self):
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    # -- ingest --------------------------------------------------------------
    def _write_with_retry(self, batch):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return process_batch(self._connection(), batch)
            except psycopg.OperationalError as exc:
                last_error = exc
                self.close()  # reconnect on the next attempt
                if attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt)
                    log.warning("db error (%s), retry %d in %.1fs", exc, attempt + 1, delay)
                    self._sleep(delay)
        raise last_error

    def ingest(self, batch):
        """Store a batch. Returns True if stored, False if spooled to disk."""
        if not batch:
            return True
        try:
            self.totals.add(self._write_with_retry(batch))
            return True
        except psycopg.OperationalError:
            self._spool(batch)
            return False

    # -- spool ---------------------------------------------------------------
    def _spool(self, batch):
        os.makedirs(os.path.dirname(self.spool_path) or ".", exist_ok=True)
        with open(self.spool_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(batch) + "\n")
        self.spooled_batches += 1
        log.error("database unavailable, spooled %d messages to %s", len(batch), self.spool_path)

    def flush_spool(self):
        """Replay spooled batches in order. Returns the number replayed."""
        if not os.path.exists(self.spool_path):
            return 0
        with open(self.spool_path, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        replayed = 0
        for index, line in enumerate(lines):
            try:
                self.totals.add(self._write_with_retry(json.loads(line)))
            except psycopg.OperationalError:
                remaining = lines[index:]
                with open(self.spool_path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(remaining) + "\n")
                return replayed
            replayed += 1
        os.remove(self.spool_path)
        return replayed
