# Mill Signals: rolling mill monitoring

Mono Edge signal analytics challenge. Two synthetic rolling mills send six PLC
signals every 20 ms. A Python pipeline stores them in Postgres, a detector
finds cobble incidents, and a Next.js app lets signed-in operators watch the
mills live, explore history and investigate incidents.

## Demo access

| | |
|---|---|
| **Live app** | https://mono-edge-signals-seven.vercel.app |
| **Email** | `demo@millsignals.dev` |
| **Password** | `MillDemo2026!` |

Every page requires login. Use the account above, or click "No account? Sign
up" on the login page and register with any email and a password of 6 or more
characters (no email confirmation needed).

A quick tour for reviewers:

1. **Live**: the hosted app replays the stored 10 minute loop on the wall
   clock (badge "REPLAY"). On RM-01 a cobble fires every minute at :30, so
   within a minute the status turns red, an INCIDENT banner appears and the
   alert shows in the side panel with its time, affected signals and reason.
   Switch mills with the dropdown.
2. **History**: pick a mill, a signal and a time range, or use the shortcuts
   (whole loop, a cobble, the load change, the speed step). Red bands mark
   incidents; the table compares normal periods with incident periods.
3. **Incidents**: every stored alert. "Explore" opens all six signals 30 s
   either side of the incident with peaks against normal values.

### Screenshots

**Live monitoring** during a cobble on RM-01: status INCIDENT, the alert with
its reason, and the incident window shaded red on every chart.

![Live monitoring during an incident](docs/screenshots/live.png)

**Historical analytics**: motor speed over the whole loop from 1 s rollups.
The line is the average, the band is min to max, red bands are detected
incidents. The slow dip around 7:00 is the legitimate speed step, which does
not alert.

![Historical analytics](docs/screenshots/history.png)

**Incident view**: all six signals 30 s either side of the 2:30 cobble, which
lands right after the load change ramp, with peaks against normal values.

![Incident view](docs/screenshots/incident.png)

**Incident history** across both mills.

![Incident history](docs/screenshots/incidents.png)

If the app shows a database connection error, the free Supabase project has
paused after a week without traffic and needs to be resumed.

## Data pipeline

How a 20 ms PLC reading gets from the simulator into the tables the app reads.

```
 generator          cleaning              batch writer (1 transaction)           after load
 ---------          --------              ----------------------------           ----------
 1 wide JSON  --->  parse timestamp  --->  raw_readings        (as received)  --> rollup.py
 message per        check mill_id          processed_readings  (typed, hourly      1 s min/avg/max
 20 ms tick         types + ranges          partitions)                            -> historical_rollups
 (6 signals)        reject reasons    --->  rejected_readings   (with reason)  --> detector
                                                                                    -> incidents
     batches of 500 messages (10 s of data)                                         -> incident_snapshots
     retry 0.5 s, 1 s, 2 s, 4 s, then spool to spool/pending_batches.jsonl
```

1. **Generate.** `simulator/generator.py` builds the 10 minute loop per mill
   with numpy and turns each tick into one wide JSON message, the shape a PLC
   gateway would send. The seeder also injects faults (dropped samples, nulls,
   a -9999 sentinel, numbers as text, garbage timestamps).
2. **Clean.** `simulator/cleaning.py` turns a message into a typed row plus
   any problems. A bad field becomes NULL and is logged; a message with no
   usable timestamp or mill is refused whole. Every refusal has a reason.
3. **Write.** `simulator/pipeline.py` writes raw, processed and rejects for a
   batch in one transaction, creating hourly partitions as needed. Every
   insert is `ON CONFLICT DO NOTHING`, so a retried batch or a re-run seed
   adds nothing.
4. **Aggregate.** `simulator/rollup.py` builds 1 second min/avg/max per signal
   from processed rows (upsert, re-runnable).
5. **Detect.** `detector/store.py` runs the cobble detector over processed
   rows and stores incidents, each with a full resolution snapshot from 30 s
   before to 30 s after.

### Pipeline tech stack

| Layer | Tool | Role |
|---|---|---|
| Language | Python 3.10+ | simulator, cleaning, writer, detector in one codebase |
| Data generation | numpy | vectorised signal model, deterministic per seed |
| Database driver | psycopg 3 (`executemany`) | batched parameterised inserts, one transaction per batch |
| Storage | PostgreSQL 16 (Docker) / 17 (Supabase) | raw JSONB, typed time series, rollups, incidents in one database |
| Partitioning | native range partitions by hour | retention by dropping a partition, smaller indexes per hour |
| Downsampling | `date_bin` in SQL | server side bucketing for every chart |
| Tests | pytest | cleaning rules, generator ground truth, detector, DB integration |

### Trade-offs

| Decision | Chosen | Alternative | Why, and when to switch |
|---|---|---|---|
| Transport | Direct batched inserts | Kafka, MQTT broker | About 50 rows/s per mill is tiny for Postgres. A broker adds a cluster to run for no gain at this volume. Add one when there are many mills, several consumers of the same stream, or producers that must not block on the database. |
| Processing model | Micro-batches of 500 (10 s) | Row by row streaming, Spark/Flink | Batching cuts database round trips and transactions by orders of magnitude and makes each batch atomic. Costs up to 10 s of latency on the write side, fine for monitoring. A stream processor pays off for windowed joins across many mills, not here. |
| Delivery guarantee | At-least-once + idempotent writes | Exactly-once protocol | Retries can resend a batch, and conflict keys make the duplicate a no-op, so the result is effectively once with no coordination. |
| Outage handling | Retry with backoff, then local spool file | Durable queue | The spool keeps data through a long database outage with zero infrastructure. It lives on one disk, so a lost laptop loses the spool; a broker would fix that. |
| Storage engine | Plain Postgres, hourly partitions | TimescaleDB, InfluxDB, ClickHouse | No extension, so it runs on any host including Supabase free tier. The cost: no column compression, and continuous aggregates are replaced by a hand built rollup table. Switch at billions of rows or when storage cost matters. |
| Table shape | Wide: one row per timestamp, six columns | Long: one row per signal reading | Matches how the PLC sends data, 6x fewer rows, simple queries. Adding a signal needs a migration; long format would not. |
| Raw layer | Keep every message as JSONB | Drop bad messages | Nothing is lost and cleaning can be re-run, at about 460 bytes per row (roughly 2 GB per mill per day at full rate). In production raw would move to cheap object storage after a few days. |
| Rollups | 1 s min/avg/max, built after load | Averages only, or compute at query time | Min and max keep cobble spikes visible after aggregation. Built in batch here; with live data it would run every few seconds or as a continuous aggregate. |
| Detection | Rule based state machine | ML anomaly model | Explainable reason text, no training data needed, tested against known ground truth. Thresholds are hand tuned to this data; a model would need labelled real incidents. |

## Repository layout

```
simulator/          signal generator, cleaning rules, batch writer, rollups, seed CLI
detector/           cobble detector (cobble.py, pure logic) and its database runner (store.py)
db/                 schema.sql (all tables) and supabase_lockdown.sql (hosted only)
tests/              pytest: generator, cleaning, detector, database integration
web/                Next.js app
  src/proxy.ts      login check for every page and API route
  src/app/api/      live, history, incidents and mills endpoints
  src/app/          Live, History, Incidents, incident view and login pages
  src/lib/          database client, signal metadata, Supabase config
docs/screenshots/   images used in this README
docker-compose.yml  local Postgres
```

## Local setup

Needs Python 3.10 or newer, Node.js 20 or newer, and Postgres 16 or newer.

```bash
# 1. Database
docker compose up -d                       # Postgres 16 on localhost:5432 (mill / mill / millsignals)

# 2. Python simulator, pipeline and detector
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export DATABASE_URL=postgresql://mill:mill@localhost:5432/millsignals

# 3. Load data (see the next section)
python -m simulator.seed --reset

# 4. Web app
cd web
npm install
cp .env.example .env.local                 # DATABASE_URL already points at the local database
npm run dev                                # http://localhost:3000
```

With the two Supabase variables in `web/.env.local` left empty, local
development runs without login (the header says "auth off"). A production
build refuses every request until they are set, so a missing setting can never
expose the app.

No Docker? Any Postgres works, for example on macOS:
`brew install postgresql@16 && brew services start postgresql@16`, then create
a `mill` role with password `mill` and a `millsignals` database.

**Tests**

```bash
python -m pytest tests                     # unit tests, no database needed
TEST_DATABASE_URL=postgresql://mill:mill@localhost:5432/millsignals_test python -m pytest tests
```

The database tests wipe the tables, so point `TEST_DATABASE_URL` at a scratch
database, never at the one the app uses.

## Starting and replaying the simulator

The simulator generates a deterministic 10 minute loop per mill (same seed,
same data every time) and pushes it through the real ingestion pipeline:
cleaning, raw and processed tables, 1 second rollups, then the cobble
detector.

```bash
python -m simulator.seed                   # load every mill (safe to repeat: inserts are idempotent)
python -m simulator.seed --reset           # wipe all tables first, then load every mill
python -m simulator.seed --mill RM-02      # load one mill only (repeatable flag)
python -m simulator.seed --no-faults       # clean data, no injected faults
python -m detector.store --mill RM-01      # re-run detection on stored data (also idempotent)
```

The loop is stored at a fixed synthetic date (2026-01-01 00:00 to 00:10 UTC),
so history and incident timestamps are stable.

**Replay.** The Live page replays the stored loop with no extra process:
`loop position = now mod 10 minutes`. Every viewer sees the same moment, the
server keeps no state, and alerts appear as the replay reaches them. To replay
from scratch, run `python -m simulator.seed --reset` again; the data and
incidents come out identical.

**Live mode.** If the newest stored row for a mill is less than 10 s old, the
Live page switches that mill to real time data with a "LIVE" badge instead of
the replay. The seeder writes the loop at its fixed date, so locally and on
the hosted demo you will see "REPLAY".

**Loading the hosted database.** Point `DATABASE_URL` at the cloud Postgres
and run the same seed command (see Deployment).

## Architecture

```
  LAPTOP (Python)                    POSTGRES                    VERCEL (Next.js)

  generator  20 ms ticks                                         proxy.ts  login check
      |                                                              |
  cleaning   types, ranges   --->  raw_readings                 /api/live       --> Live page
      |                            processed_readings  <------  /api/history    --> History page
  pipeline   batch, retry,         historical_rollups           /api/incidents  --> Incidents
             spool                 incidents                         |
      |                            incident_snapshots           Supabase Auth
  detector   cobble rules  --->  (writes incidents)              (email + password)
```

* **Write side (Python).** Generator, cleaning, batch writer, rollups and
  detector, described in [Data pipeline](#data-pipeline).
* **Storage (Postgres).** Bronze/silver/gold style layers in one database.
  Processed rows are partitioned by hour, so retention is a cheap partition
  drop. Locally it runs in Docker; the hosted demo uses Supabase Postgres with
  the same schema and a different `DATABASE_URL`.
* **Read side (Next.js on Vercel).** API routes query Postgres directly and
  downsample on the server with `date_bin`, so the browser only receives a few
  hundred points per chart. The Live page polls once a second. Supabase Auth
  handles sign-up and sign-in, and `proxy.ts` checks the session on every
  page and API request.

### App stack and why

| Part | Choice | Why |
|---|---|---|
| Database | Postgres (16 locally, 17 on Supabase) | Time series in a wide table, hourly partitions for cheap retention, `date_bin` for downsampling, JSONB for the raw layer. One `DATABASE_URL` switches local vs cloud. No extension needed, so any host works. |
| Hosted database | Supabase (free tier) | Postgres plus authentication in one free project, so one account covers both. Both seed loops take about 42 MB, well inside the 500 MB limit. |
| Web app | Next.js 16 (App Router, TypeScript) | Pages and API routes in one project, deploys to Vercel with no extra setup. API routes talk to Postgres directly with the `postgres` driver, so the SQL is visible and easy to explain. |
| Authentication | Supabase Auth, email and password | Sign-up, sign-in, hashed passwords and session cookies already done and maintained. Writing that by hand is where security bugs live, and it would not show anything about data engineering. |
| Charts | Recharts | Simple React API and enough for the point counts here, because the server downsamples first. With raw 20 ms data in the browser a canvas library such as uPlot would be the better pick. |
| Live updates | Polling every 1 s | Vercel functions are short lived, so held-open streams (SSE, WebSocket) are a poor fit. A 1 s poll is cheap, survives reconnects and is fast enough for operators. |
| Hosting | Vercel | Free, deploys from GitHub on every push. |

## Anomaly detection approach

The detector looks for **cobbles**: the strip jams, motor speed collapses and
the stand starts shaking. It requires a sudden speed collapse **and** a
vibration jump at the same time. Neither alone is enough, which is what keeps
legitimate operating changes quiet:

| Situation | Speed vs baseline | Vibration vs baseline | Result |
|---|---|---|---|
| Cobble | below 80 percent | more than +1.5 mm/s | incident |
| Load change | flat | flat | nothing (current, torque and force alone never trigger) |
| Speed setpoint change | moves about 5 rpm/s, baseline follows | flat | nothing |
| Single noisy sample | brief | brief | nothing (needs 0.2 s in a row) |

* **Baseline**: rolling median of the last 5 s of normal samples per signal,
  per mill. Comparing against a baseline instead of a fixed threshold is why
  slow setpoint changes do not alert and why the same thresholds work on both
  mills. The baseline is frozen while an incident is open.
* **Open**: the cobble condition holds for 10 consecutive samples (0.2 s).
* **Close (hysteresis)**: speed back above 95 percent and vibration within
  1 mm/s of baseline continuously for 3 s, because speed wobbles while it
  recovers.
* **Output**: one incident per cobble with start, end, affected signals
  (speed and vibration, plus current, torque or force if they spiked more
  than 15 percent), peaks against baseline, and a reason such as "motor speed
  fell from 1000 to 351 rpm (-65%) while vibration rose to 7.9 mm/s (normal
  2.0); current +59%, torque +49%, force +24%".
* **Streaming and idempotent**: `CobbleDetector.update(row)` is a state
  machine, so the same code runs over stored history or live rows. Incidents
  are upserted on `(mill_id, started_at)`, so re-running never duplicates.

**Results**: RM-01 10 of 10 and RM-02 4 of 4 cobbles detected, each opening
0.10 to 0.16 s after the cobble starts, with no incidents during either mill's
load change or speed step. The tests repeat this on other noise seeds with
data faults injected.

**Limits**: thresholds are tuned to the synthetic data; on a real mill they
would be set per mill from historical incidents. A cobble while speed is
already ramping hard, or a slow jam without a vibration jump, would need extra
rules.

Code: `detector/cobble.py` (pure logic) and `detector/store.py` (database).
Thresholds are constants at the top of `detector/cobble.py`.

---

# Details

## The 10 minute loop

Two mills, six signals each (motor speed, motor current, torque, rolling
force, vibration, temperature), 30,000 ticks per mill per loop. Each mill has
its own operating point and its own day.

**RM-01** (roughing stand, 1000 rpm, 150 A, 40 kN.m, 2000 kN)

| Time | Event | What the data does |
|---|---|---|
| every 60 s from 0:30 | Cobble (10 per loop) | speed dips to about 35 percent with a wobble, vibration jumps to 6 to 9 mm/s, current/torque/force spike briefly; normal again after about 9 s |
| 2:15 to 3:30 | Legitimate load change | current, torque, rolling force rise about 40 percent; speed and vibration stay flat |
| 7:00 to 8:10 | Legitimate speed setpoint change | speed steps down about 10 percent smoothly and back |

The cobbles at 2:30 and 3:30 sit at the edges of the load change on purpose.

**RM-02** (finishing stand, 1200 rpm, 110 A, 25 kN.m, 1500 kN)

| Time | Event | What the data does |
|---|---|---|
| 1:10, 2:30, 4:40, 8:20 | Cobble (4 per loop) | same pattern as RM-01, scaled to this stand |
| 1:45 to 3:20 | Legitimate speed setpoint change | speed steps **up** about 8 percent and back |
| 5:30 to 6:45 | Legitimate load change | current, torque, rolling force rise about 30 percent |

The 2:30 cobble on RM-02 happens while speed sits at the raised setpoint, so
the drop is measured from 1298 rpm, not from the usual 1200.

Mill profiles and event times live in `simulator/config.py` (`MILLS`), and
`generator.ground_truth(mill)` returns them so the detector can be tested
against known answers. Adding a mill is one more profile there.

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

## Web app

Code is in `web/`. Pages: **Live** (status, latest values, live charts,
alerts), **History** (signal and time range, trend with min to max band,
normal vs abnormal stats), **Incidents** (alert history with a mill filter)
and an **incident view** (all signals 30 s either side, peaks vs normal).

How the API keeps the browser light:

| Endpoint | Reads | Downsampling |
|---|---|---|
| `/api/live` | `processed_readings` | 200 ms averages (300 points per minute) |
| `/api/history`, up to 5 min | `processed_readings` | full 20 ms or binned to about 1500 points, with min and max |
| `/api/history`, longer | `historical_rollups` | 1 s or wider buckets, about 1000 points, with min and max |
| `/api/incidents/:id` | `incident_snapshots` | 100 ms averages |

Min and max travel with every averaged point, so a cobble spike is still
visible on a 10 minute chart. In replay, a live window that crosses the loop
start is stitched from the end of the loop.

## Deployment

1. **Supabase**: create a free project. In Authentication > Sign In / Providers
   > Email, turn off "Confirm email" so demo sign-ups work at once.
2. **Load the data** from the laptop, using the Session pooler connection
   string (Project Settings > Database):
   ```bash
   export DATABASE_URL='postgresql://postgres.<ref>:<password>@<region>.pooler.supabase.com:5432/postgres'
   python -m simulator.seed --reset
   psql "$DATABASE_URL" -f db/supabase_lockdown.sql
   ```
   The lockdown script stops Supabase's public REST API from reading the
   tables (the app connects to Postgres directly and does not need it).
3. **Vercel**: import the GitHub repo, set Root Directory to `web`, and add
   the environment variables:
   * `DATABASE_URL`: the Transaction pooler string (port 6543)
   * `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`: from
     Project Settings > API

   `web/vercel.json` pins the functions to Tokyo (`hnd1`), the same region as
   the database, because every API call makes a few queries and cross-region
   round trips would add up.
4. Sign up once on the deployed app to create the demo account.

The Vercel project is connected to this GitHub repo, so every push to `main`
deploys to production and other branches get preview URLs. A failed build
never replaces the running site.
