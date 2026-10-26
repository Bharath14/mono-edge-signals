-- Mono Edge signal analytics: schema (idempotent, safe to run repeatedly)
--
-- Layers
--   raw_readings         exactly what arrived, loosely typed, never refuses a message
--   processed_readings   cleaned and typed, one row per timestamp, partitioned by hour
--   historical_rollups   1 second min/avg/max per signal, built from processed
--   rejected_readings    anything the cleaning step refused or quarantined, with a reason
--   incidents            detected incidents (written by the detector, added later)
--   incident_snapshots   full resolution signals kept around each incident

-- 1. RAW ---------------------------------------------------------------------
-- ts_text is the timestamp string exactly as received, so even a malformed
-- timestamp can be stored. payload_md5 is a hash of the message, so:
--   * replaying the exact same message is a no-op (idempotent), and
--   * two different messages that share a timestamp, or share the same garbage
--     timestamp, are both kept. Raw never silently drops anything.
CREATE TABLE IF NOT EXISTS raw_readings (
  mill_id     text        NOT NULL,
  ts_text     text        NOT NULL,
  payload     jsonb       NOT NULL,
  payload_md5 text        GENERATED ALWAYS AS (md5(payload::text)) STORED,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (mill_id, ts_text, payload_md5)
);

-- 2. PROCESSED ---------------------------------------------------------------
-- Partitions are created by the pipeline (one per hour, named
-- processed_readings_YYYYMMDDHH). Retention = drop old partitions.
CREATE TABLE IF NOT EXISTS processed_readings (
  mill_id        text             NOT NULL,
  ts             timestamptz      NOT NULL,
  motor_speed    double precision,  -- rpm
  motor_current  double precision,  -- A
  torque         double precision,  -- kN.m
  rolling_force  double precision,  -- kN
  vibration      double precision,  -- mm/s
  temperature    double precision,  -- degC
  PRIMARY KEY (mill_id, ts)
) PARTITION BY RANGE (ts);

-- 3. HISTORICAL ROLLUPS ------------------------------------------------------
CREATE TABLE IF NOT EXISTS historical_rollups (
  mill_id        text        NOT NULL,
  bucket_ts      timestamptz NOT NULL,  -- start of the 1 second bucket
  speed_avg      double precision, speed_min   double precision, speed_max   double precision,
  current_avg    double precision, current_min double precision, current_max double precision,
  torque_avg     double precision, torque_min  double precision, torque_max  double precision,
  force_avg      double precision, force_min   double precision, force_max   double precision,
  vib_avg        double precision, vib_min     double precision, vib_max     double precision,
  temp_avg       double precision, temp_min    double precision, temp_max    double precision,
  sample_count   integer     NOT NULL,
  PRIMARY KEY (mill_id, bucket_ts)
);

-- 4. REJECTS -----------------------------------------------------------------
-- One row per problem. A message with one bad field is still kept in
-- processed (that field becomes NULL) and the problem is logged here.
CREATE TABLE IF NOT EXISTS rejected_readings (
  id          bigserial   PRIMARY KEY,
  mill_id     text        NOT NULL DEFAULT '',
  ts_text     text        NOT NULL DEFAULT '',
  payload     jsonb       NOT NULL,
  payload_md5 text        GENERATED ALWAYS AS (md5(payload::text)) STORED,
  reason      text        NOT NULL,
  rejected_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (mill_id, ts_text, reason, payload_md5)
);

-- 5. INCIDENTS ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidents (
  id               bigserial   PRIMARY KEY,
  mill_id          text        NOT NULL,
  started_at       timestamptz NOT NULL,
  ended_at         timestamptz,            -- NULL while the incident is open
  affected_signals text[]      NOT NULL,
  reason           text        NOT NULL,
  peak_values      jsonb,
  UNIQUE (mill_id, started_at)
);

CREATE TABLE IF NOT EXISTS incident_snapshots (
  incident_id    bigint           NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  mill_id        text             NOT NULL,
  ts             timestamptz      NOT NULL,
  motor_speed    double precision,
  motor_current  double precision,
  torque         double precision,
  rolling_force  double precision,
  vibration      double precision,
  temperature    double precision,
  PRIMARY KEY (incident_id, mill_id, ts)
);
