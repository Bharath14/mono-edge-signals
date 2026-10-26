import type { NextRequest } from "next/server";
import { badRequest, parseTime, sql } from "@/lib/db";
import { DEFAULT_MILL, getSignal } from "@/lib/signals";

// Historical data for one signal and time range, by real stored timestamps.
//   range up to 5 min   full resolution processed rows, binned to about 1500 points
//   longer ranges       1 s rollups, re-binned to about 1000 points
// Every point carries min and max as well as avg, so a short cobble spike is
// still visible after aggregation. Incidents in the range are returned so the
// chart can shade abnormal periods, with stats split into normal vs abnormal.

const FULL_RES_MAX_MS = 5 * 60_000;
const MAX_RANGE_MS = 7 * 24 * 3_600_000;

type Point = { t: number; avg: number | null; min: number | null; max: number | null };

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const mill = params.get("mill") || DEFAULT_MILL;
  const signal = getSignal(params.get("signal"));
  const from = parseTime(params.get("from"));
  const to = parseTime(params.get("to"));
  if (!signal) return badRequest("unknown signal");
  if (!from || !to || to <= from) return badRequest("from and to must be valid times, from before to");
  const spanMs = to.getTime() - from.getTime();
  if (spanMs > MAX_RANGE_MS) return badRequest("range is limited to 7 days");

  let points: Point[];
  let source: string;
  let bucketMs: number;
  if (spanMs <= FULL_RES_MAX_MS) {
    bucketMs = Math.max(20, Math.ceil(spanMs / 1500 / 20) * 20);
    const col = sql(signal.key);
    points = await sql<Point[]>`
      SELECT (extract(epoch FROM date_bin(${bucketMs + " milliseconds"}::interval, ts, timestamptz '2000-01-01')) * 1000)::float8 AS t,
             avg(${col}) AS avg, min(${col}) AS min, max(${col}) AS max
      FROM processed_readings
      WHERE mill_id = ${mill} AND ts >= ${from} AND ts < ${to}
      GROUP BY 1 ORDER BY 1`;
    source = bucketMs === 20 ? "processed (full resolution)" : `processed, ${bucketMs} ms buckets`;
  } else {
    const bucketS = Math.max(1, Math.ceil(spanMs / 1000 / 1000));
    bucketMs = bucketS * 1000;
    const avg = sql(`${signal.rollup}_avg`);
    const min = sql(`${signal.rollup}_min`);
    const max = sql(`${signal.rollup}_max`);
    points = await sql<Point[]>`
      SELECT (extract(epoch FROM date_bin(${bucketS + " seconds"}::interval, bucket_ts, timestamptz '2000-01-01')) * 1000)::float8 AS t,
             sum(${avg} * sample_count) / nullif(sum(CASE WHEN ${avg} IS NOT NULL THEN sample_count END), 0) AS avg,
             min(${min}) AS min, max(${max}) AS max
      FROM historical_rollups
      WHERE mill_id = ${mill} AND bucket_ts >= ${from} AND bucket_ts < ${to}
      GROUP BY 1 ORDER BY 1`;
    source = bucketS === 1 ? "1 s rollups" : `1 s rollups, ${bucketS} s buckets`;
  }

  const incidents = await sql`
    SELECT id, started_at, ended_at, affected_signals, reason
    FROM incidents
    WHERE mill_id = ${mill} AND started_at < ${to} AND coalesce(ended_at, started_at) >= ${from}
    ORDER BY started_at`;
  const spans = incidents.map((i) => [
    (i.started_at as Date).getTime(),
    ((i.ended_at ?? i.started_at) as Date).getTime(),
  ]);
  // A bucket is abnormal if any part of it overlaps an incident.
  const isAbnormal = (t: number) => spans.some(([s, e]) => t <= e && t + bucketMs > s);

  return Response.json({
    mill,
    signal: signal.key,
    source,
    bucketMs,
    points,
    incidents,
    stats: {
      normal: summarize(points.filter((p) => !isAbnormal(p.t))),
      abnormal: summarize(points.filter((p) => isAbnormal(p.t))),
    },
  });
}

function summarize(points: Point[]) {
  const avgs = points.map((p) => p.avg).filter((v): v is number => v !== null);
  const mins = points.map((p) => p.min).filter((v): v is number => v !== null);
  const maxs = points.map((p) => p.max).filter((v): v is number => v !== null);
  if (!avgs.length) return null;
  return {
    points: avgs.length,
    avg: avgs.reduce((a, b) => a + b, 0) / avgs.length,
    min: Math.min(...mins),
    max: Math.max(...maxs),
  };
}
