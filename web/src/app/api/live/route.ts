import type { NextRequest } from "next/server";
import { sql } from "@/lib/db";
import {
  DEFAULT_MILL,
  LIVE_THRESHOLD_MS,
  LOOP_END_MS,
  LOOP_MS,
  LOOP_START_MS,
  replayNow,
} from "@/lib/signals";

// Live dashboard data: the last `window` seconds of every signal, averaged
// into 200 ms buckets, plus status and the alerts fired so far.
//
// Two modes:
//   LIVE    a simulator wrote a row in the last 10 s, so show real time.
//   REPLAY  otherwise, replay the stored seed loop. The loop position comes
//           from the wall clock, so every viewer sees the same moment and the
//           server keeps no state. A window that crosses the loop start is
//           stitched from the end of the loop.
//
// Point timestamps are returned on the real wall clock (ms), so the chart axis
// shows current time in both modes.

const BUCKET = "200 milliseconds";

type Segment = { from: number; to: number; shift: number };

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const mill = params.get("mill") || DEFAULT_MILL;
  const windowS = Math.min(Math.max(Number(params.get("window")) || 60, 10), 300);
  const windowMs = windowS * 1000;
  const nowMs = Date.now();

  const [{ latest }] = await sql<{ latest: Date | null }[]>`
    SELECT max(ts) AS latest FROM processed_readings WHERE mill_id = ${mill}`;
  const live = latest !== null && nowMs - latest.getTime() < LIVE_THRESHOLD_MS;

  const virtualNow = live ? nowMs : replayNow(nowMs);
  const start = virtualNow - windowMs;
  const segments: Segment[] =
    live || start >= LOOP_START_MS
      ? [{ from: start, to: virtualNow, shift: 0 }]
      : [
          { from: LOOP_END_MS - (LOOP_START_MS - start), to: LOOP_END_MS, shift: -LOOP_MS },
          { from: LOOP_START_MS, to: virtualNow, shift: 0 },
        ];

  const points = [];
  for (const seg of segments) {
    const rows = await sql<Record<string, number>[]>`
      SELECT (extract(epoch FROM date_bin(${BUCKET}::interval, ts, timestamptz '2000-01-01')) * 1000)::float8 AS t,
             avg(motor_speed) AS motor_speed, avg(motor_current) AS motor_current,
             avg(torque) AS torque, avg(rolling_force) AS rolling_force,
             avg(vibration) AS vibration, avg(temperature) AS temperature
      FROM processed_readings
      WHERE mill_id = ${mill} AND ts >= ${new Date(seg.from)} AND ts <= ${new Date(seg.to)}
      GROUP BY 1 ORDER BY 1`;
    for (const r of rows) points.push({ ...r, t: nowMs + (r.t + seg.shift - virtualNow) });
  }

  // Alerts: in replay, the ones fired so far in this pass of the loop, so each
  // cobble alert appears in front of the viewer as the replay reaches it.
  const alertsFrom = live ? new Date(nowMs - 3_600_000) : new Date(LOOP_START_MS);
  const alertRows = await sql`
    SELECT id, started_at, ended_at, affected_signals, reason
    FROM incidents
    WHERE mill_id = ${mill} AND started_at >= ${alertsFrom} AND started_at <= ${new Date(virtualNow)}
    ORDER BY started_at DESC
    LIMIT 20`;
  const alerts = alertRows.map((a) => {
    const started = (a.started_at as Date).getTime();
    const ended = a.ended_at ? (a.ended_at as Date).getTime() : null;
    return {
      id: a.id,
      started_at: a.started_at,
      ended_at: a.ended_at,
      affected_signals: a.affected_signals,
      reason: a.reason,
      fired_at: nowMs + (started - virtualNow),
      open: ended === null || ended > virtualNow,
    };
  });

  return Response.json({
    mill,
    mode: live ? "LIVE" : "REPLAY",
    serverNow: nowMs,
    virtualNow: new Date(virtualNow).toISOString(),
    windowS,
    status: alerts.some((a) => a.open) ? "INCIDENT" : points.length ? "RUNNING" : "NO DATA",
    latest: points.at(-1) ?? null,
    points,
    alerts,
  });
}
