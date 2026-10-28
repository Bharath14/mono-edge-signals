# Mill Signals: rolling mill monitoring

Mono Edge signal analytics challenge. A synthetic rolling mill sends six PLC
signals every 20 ms. A Python pipeline stores them in Postgres, a detector
finds cobble incidents, and a Next.js app lets signed-in operators watch the
mill live, explore history and investigate incidents.

* **Live demo:** https://mono-edge-signals-seven.vercel.app
* **Demo login:** `demo@millsignals.dev` / `MillDemo2026!` (or sign up with any email)

The hosted Live page replays the stored 10 minute seed loop (badge "REPLAY"),
so a cobble alert fires about once a minute while you watch.

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

The simulator and detector run on a laptop. Locally they write to Postgres in
Docker; for the hosted demo the same seed is loaded into Supabase Postgres by
pointing `DATABASE_URL` at it. The web app only reads.

## Stack and why

| Part | Choice | Why |
|---|---|---|
| Simulator, pipeline, detector | Python 3, psycopg 3 | Quick to write and test, and the detector is plain code that runs the same over history and live rows. |
| Message transport | None, batched inserts | About 50 rows per second fits easily in plain batched inserts. A broker (Kafka or similar) would sit between producer and writer at many mills or when several consumers need the stream. |
| Database | Postgres 16 (Docker locally, Supabase hosted) | Time series in a wide table, hourly partitions for cheap retention, `date_bin` for downsampling, JSONB for the raw layer. One `DATABASE_URL` switches local vs cloud. No extension needed, so any host works. |
| Hosted database | Supabase (free tier) | Postgres plus authentication in one free project, so one account covers both. The seed loop is about 18 MB, well inside the 500 MB limit. |
| Web app | Next.js 16 (App Router, TypeScript) | Pages and API routes in one project, deploys to Vercel with no extra setup. API routes talk to Postgres directly with the `postgres` driver, so the SQL is visible and easy to explain. |
| Authentication | Supabase Auth, email and password | Sign-up, sign-in, hashed passwords and session cookies already done and maintained. Writing that by hand is where security bugs live, and it would not show anything about data engineering. The check runs in `proxy.ts` on every page and API request. |
| Charts | Recharts | Simple React API and enough for the point counts here, because the server downsamples first (about 300 points per live chart, 600 to 1500 for history). With raw 20 ms data in the browser a canvas library such as uPlot would be the better pick. |
| Live updates | Polling every 1 s | Vercel functions are short lived, so held-open streams (SSE, WebSocket) are a poor fit. A 1 s poll is cheap, survives reconnects and is fast enough for operators. |
| Hosting | Vercel | Free, deploys from GitHub on every push. |

## Quick start

```bash
docker compose up -d                       # Postgres 16 on localhost:5432
python3 -m venv .venv && source .venv/bin/activate   # Python 3.10 or newer
pip install -r requirements.txt
cp .env.example .env                       # DATABASE_URL for the local container
export DATABASE_URL=postgresql://mill:mill@localhost:5432/millsignals

python -m simulator.seed --reset           # build and load the 10 minute loop for every mill, then detect incidents
python -m simulator.seed --mill RM-02      # just one mill (repeatable)
python -m detector.store --mill RM-02      # re-run detection on its own (safe to repeat)
python -m pytest tests                     # unit tests (no database needed)
TEST_DATABASE_URL=postgresql://mill:mill@localhost:5432/millsignals_test python -m pytest tests   # plus database tests

cd web && npm install && cp .env.example .env.local && npm run dev   # web app on http://localhost:3000
```

The database tests wipe the tables, so point `TEST_DATABASE_URL` at a scratch
database. Running the seed twice is safe: every insert is idempotent.

No Docker? Any Postgres 16 works, for example on macOS:
`brew install postgresql@16 && brew services start postgresql@16`, then create
a `mill` role with password `mill` and a `millsignals` database.

## The 10 minute loop

Two mills, six signals each, one reading every 20 ms (30,000 ticks per mill
per loop). Each mill has its own operating point and its own day, so the
detector is tested on two different shapes of normal.

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
the drop is measured from 1298 rpm, not from the usual 1200. That only works
because the detector compares against a rolling baseline.

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

Results on the seed loop: RM-01 10 of 10 and RM-02 4 of 4 cobbles detected,
each opening 0.10 to 0.16 s after the cobble starts, and no incidents during
either mill's load change or speed step (down on RM-01, up on RM-02). The same
thresholds work on both stands because everything is relative to each mill's
own baseline. The tests repeat this on other noise seeds with data faults
injected. Thresholds are constants at the top of `detector/cobble.py`.

Limits: the thresholds are tuned to the synthetic data. On a real mill they
would be set from historical incidents and per mill. A cobble that happens
while speed is already ramping hard, or a slow jam without a vibration jump,
would need extra rules.

## Web app

Code is in `web/`. Pages: **Live** (status, latest values, live charts,
alerts), **History** (signal and time range, trend with min to max band,
normal vs abnormal stats), **Incidents** (alert history) and an **incident
view** (all signals 30 s either side, peaks vs normal).

### Run locally

```bash
cd web
npm install
cp .env.example .env.local     # DATABASE_URL already points at the local database
npm run dev                    # http://localhost:3000
```

With the two Supabase variables empty, local development runs without login
(the header says "auth off"). A production build refuses every request until
they are set, so a missing setting can never expose the app.

### Live vs replay

The hosted app cannot reach a simulator on a laptop, so the Live page has two
modes, chosen per request:

* **LIVE**: the newest stored row is less than 10 s old, so a simulator is
  streaming. Charts show the last 30 s to 2 min of real data.
* **REPLAY (demo loop)**: otherwise the stored 10 minute seed loop is replayed
  on the wall clock: `loop position = now mod 10 min`. Every viewer sees the
  same moment, the server keeps no state, and a window that crosses the loop
  start is stitched from the end of the loop.

Alerts appear as the replay reaches them, so a reviewer sees a cobble alert
fire within a minute of opening the page. History and the incident pages
always show stored data by its real timestamps.

### How the API keeps the browser light

| Endpoint | Reads | Downsampling |
|---|---|---|
| `/api/live` | `processed_readings` | 200 ms averages (300 points per minute) |
| `/api/history`, up to 5 min | `processed_readings` | full 20 ms or binned to about 1500 points, with min and max |
| `/api/history`, longer | `historical_rollups` | 1 s or wider buckets, about 1000 points, with min and max |
| `/api/incidents/:id` | `incident_snapshots` | 100 ms averages |

Min and max travel with every averaged point, so a cobble spike is still
visible on a 10 minute chart.

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
   the environment variables. `web/vercel.json` pins the functions to Tokyo
   (`hnd1`), the same region as the Supabase database, because every API call
   makes a few queries and cross-region round trips would add up:
   * `DATABASE_URL`: the Transaction pooler string (port 6543)
   * `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`: from
     Project Settings > API
4. Sign up once on the deployed app to create the demo account.

The Vercel project is connected to this GitHub repo with Root Directory
`web`, so every push to `main` deploys to production and other branches get
preview URLs. A failed build never replaces the running site.

Free Supabase projects pause after a week without activity. If the demo
shows a connection error, the project needs to be resumed in the dashboard.
