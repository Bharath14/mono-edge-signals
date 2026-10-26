import { badRequest, sql } from "@/lib/db";

// One incident plus the signals around it, read from incident_snapshots
// (30 s before to 30 s after, kept even after processed partitions are
// dropped). Binned to 100 ms so the charts stay light.
export async function GET(_req: Request, ctx: RouteContext<"/api/incidents/[id]">) {
  const { id } = await ctx.params;
  const incidentId = Number(id);
  if (!Number.isInteger(incidentId)) return badRequest("bad incident id");

  const [incident] = await sql`
    SELECT id, mill_id, started_at, ended_at, affected_signals, reason, peak_values
    FROM incidents WHERE id = ${incidentId}`;
  if (!incident) return Response.json({ error: "not found" }, { status: 404 });

  const points = await sql`
    SELECT (extract(epoch FROM date_bin('100 milliseconds', ts, timestamptz '2000-01-01')) * 1000)::float8 AS t,
           avg(motor_speed) AS motor_speed, avg(motor_current) AS motor_current,
           avg(torque) AS torque, avg(rolling_force) AS rolling_force,
           avg(vibration) AS vibration, avg(temperature) AS temperature
    FROM incident_snapshots
    WHERE incident_id = ${incidentId}
    GROUP BY 1 ORDER BY 1`;

  const [neighbours] = await sql`
    SELECT
      (SELECT id FROM incidents WHERE mill_id = ${incident.mill_id} AND started_at < ${incident.started_at}
         ORDER BY started_at DESC LIMIT 1) AS prev_id,
      (SELECT id FROM incidents WHERE mill_id = ${incident.mill_id} AND started_at > ${incident.started_at}
         ORDER BY started_at LIMIT 1) AS next_id`;

  return Response.json({ incident, points, ...neighbours });
}
