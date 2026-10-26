import postgres from "postgres";

// One small pool per server instance. prepare: false keeps it compatible with
// the Supabase transaction pooler (PgBouncer), which serverless functions use.
const globalForDb = globalThis as unknown as { sql?: postgres.Sql };

export const sql =
  globalForDb.sql ??
  postgres(process.env.DATABASE_URL ?? "", {
    max: 5,
    prepare: false,
    idle_timeout: 20,
    connect_timeout: 10,
  });

if (process.env.NODE_ENV !== "production") globalForDb.sql = sql;

// Shared helpers for route handlers.
export function badRequest(message: string) {
  return Response.json({ error: message }, { status: 400 });
}

export function parseTime(value: string | null): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}
