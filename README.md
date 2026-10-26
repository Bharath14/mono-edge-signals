# Mill signal simulator and ingestion pipeline

Part 1 of the Mono Edge signal analytics challenge: a synthetic rolling mill
data source, the pipeline that stores it in Postgres, and the cobble detector.
The API and dashboard come next.

## Quick start

```bash
docker compose up -d                       # Postgres 16 on localhost:5432
python3 -m venv .venv && source .venv/bin/activate   # Python 3.10 or newer
pip install -r requirements.txt
cp .env.example .env                       # DATABASE_URL for the local container
export DATABASE_URL=postgresql://mill:mill@localhost:5432/millsignals

python -m simulator.seed --reset           # build and load the 10 minute loop, then detect incidents
python -m detector.store                   # re-run detection on its own (safe to repeat)
python -m pytest tests                     # unit tests (no database needed)
TEST_DATABASE_URL=$DATABASE_URL python -m pytest tests   # plus database tests
```

The database tests wipe the tables, so point `TEST_DATABASE_URL` at a scratch
database. Running the seed twice is safe: every insert is idempotent.

No Docker? Any Postgres 16 works, for example on macOS:
`brew install postgresql@16 && brew services start postgresql@16`, then create
a `mill` role with password `mill` and a `millsignals` database.

## The 10 minute loop

One mill (`RM-01`), six signals, one reading every 20 ms (30,000 ticks).

| Time | Event | What the data does |
|---|---|---|
| every 60 s from 0:30 | Cobble (10 per loop) | speed dips to about 35 percent with a wobble, vibration jumps to 6 to 9 mm/s, current/torque/force spike briefly; normal again after about 9 s |
| 2:15 to 3:30 | Legitimate load change | current, torque, rolling force rise about 40 percent; speed and vibration stay flat |
| 7:00 to 8:10 | Legitimate speed setpoint change | speed steps down about 10 percent smoothly and back |

The cobbles at 2:30 and 3:30 sit at the edges of the load change on purpose.
Event times live in `simulator/config.py`, and `generator.ground_truth()`
returns them so the detector can be tested against known answers.

## Data layers

| Table | Purpose |
|---|---|
| `raw_readings` | Every message exactly as received (JSONB). Never refuses a message, including malformed ones. |
| `processed_readings` | Cleaned and typed, one row per timestamp, partitioned by hour. |
| `historical_rollups` | 1 second min, avg and max per signal, built from processed. |
| `rejected_readings` | Every cleaning problem with a reason. |
| `incidents` | One row per detected incident: start, end, affected signals, reason, peak values. |
| `incident_snapshots` | Full resolution rows from 30 s before to 30 s after each incident, so the incident view survives partition drops. |

Cleaning rules are documented at the top of `simulator/cleaning.py`. The seeder
injects a few faults (dropped samples, nulls, a -9999 sentinel, numeric text,
garbage timestamps) so these rules are exercised on every seed.

## Failure handling

| Failure | Behaviour |
|---|---|
| Batch retried or seed re-run | Idempotent inserts, no duplicates |
| Database slow or briefly down | Retry with exponential backoff |
| Database down longer | Batch spooled to `spool/pending_batches.jsonl`, replayed by `Ingestor.flush_spool()` |
| Malformed message | Kept in raw, logged in rejected_readings |
| Crash mid batch | One transaction per batch, so all or nothing |

## Cobble detection

Code: `detector/cobble.py` (pure logic, no database) and `detector/store.py`
(reads processed rows, writes incidents and snapshots). The seed runs it at the
end, and `python -m detector.store` runs it again on any time range.

A cobble shows up as a sudden speed collapse together with a vibration jump.
Neither alone is enough, which is what keeps legitimate changes quiet:

| Situation | Speed vs baseline | Vibration vs baseline | Result |
|---|---|---|---|
| Cobble | below 80 percent | more than +1.5 mm/s | incident |
| Load change | flat | flat | nothing (current, torque and force alone never trigger) |
| Speed setpoint change | moves about 5 rpm/s, baseline follows | flat | nothing |
| Single noisy sample | brief | brief | nothing (needs 0.2 s in a row) |

How it works:

* **Baseline**: rolling median of the last 5 s of normal samples for each
  signal. Comparing against a baseline instead of a fixed threshold is why the
  slow setpoint change does not alert. The baseline is frozen while an incident
  is open so the incident cannot drag it down.
* **Open**: speed below 80 percent of baseline and vibration more than
  1.5 mm/s above baseline for 10 consecutive samples (0.2 s).
* **Close (hysteresis)**: speed back above 95 percent and vibration within
  1 mm/s of baseline, continuously for 3 s. Speed wobbles while it recovers,
  so one good sample is not enough. The end time is when signals first came
  back to normal.
* **Output**: start, end, affected signals (speed and vibration, plus current,
  torque or force if they spiked more than 15 percent), peak values with the
  baseline, and a reason such as "motor speed fell from 1000 to 351 rpm (-65%)
  while vibration rose to 7.9 mm/s (normal 2.0); current +59%, torque +49%,
  force +24%".
* **Idempotent**: incidents are upserted on `(mill_id, started_at)` and their
  snapshots rebuilt, so re-running detection never duplicates anything.

The detector is a streaming state machine (`CobbleDetector.update(row)`), so
the same code runs over stored history and over live data as it arrives.

Results on the seed loop: 10 of 10 cobbles detected, each opening 0.10 to
0.16 s after the cobble starts, and no incidents during the load change or the
speed step. The tests repeat this on other noise seeds with data faults
injected. Thresholds are constants at the top of `detector/cobble.py`.

Limits: the thresholds are tuned to the synthetic data. On a real mill they
would be set from historical incidents and per mill. A cobble that happens
while speed is already ramping hard, or a slow jam without a vibration jump,
would need extra rules.
