import type { NextRequest } from "next/server";
import { sql } from "@/lib/db";

// Alert history, newest first. Optional ?mill= filter.
export async function GET(req: NextRequest) {
  const mill = req.nextUrl.searchParams.get("mill");
  const rows = await sql`
    SELECT id, mill_id, started_at, ended_at, affected_signals, reason, peak_values
    FROM incidents
    ${mill ? sql`WHERE mill_id = ${mill}` : sql``}
    ORDER BY started_at DESC
    LIMIT 500`;
  return Response.json({ incidents: rows });
}
