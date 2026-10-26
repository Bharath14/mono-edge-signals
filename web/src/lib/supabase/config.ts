export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
export const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

// Local development may run without Supabase (no login). Production never does:
// the proxy refuses every request if auth is not configured.
export const AUTH_CONFIGURED = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);
export const AUTH_DISABLED = !AUTH_CONFIGURED && process.env.NODE_ENV !== "production";
