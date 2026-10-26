import { sql } from "@/lib/db";

// Mills that have data, with the stored time range (from the small rollup
// table, not the large processed one).
export async function GET() {
  const mills = await sql`
    SELECT mill_id, min(bucket_ts) AS first_ts, max(bucket_ts) + interval '1 second' AS last_ts
    FROM historical_rollups
    GROUP BY mill_id
    ORDER BY mill_id`;
  return Response.json({ mills });
}
