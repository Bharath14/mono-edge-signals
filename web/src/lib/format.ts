// Stored data (history, incidents) is shown in UTC so it matches the database.
// The live view uses the viewer's local clock.

export function fmtUtc(value: string | number | Date, withMs = false): string {
  const iso = new Date(value).toISOString();
  return iso.slice(0, 10) + " " + iso.slice(11, withMs ? 23 : 19);
}

export function fmtUtcTime(ms: number, withMs = false): string {
  return new Date(ms).toISOString().slice(11, withMs ? 21 : 19);
}

export function fmtLocalTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour12: false });
}

export function fmtNum(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "–" : v.toFixed(digits);
}

export function fmtDuration(start: string, end: string | null): string {
  if (!end) return "open";
  return ((new Date(end).getTime() - new Date(start).getTime()) / 1000).toFixed(1) + " s";
}

// <input type="datetime-local"> values, treated as UTC.
export function toUtcInput(ms: number): string {
  return new Date(ms).toISOString().slice(0, 19);
}

export function fromUtcInput(value: string): number {
  return new Date(value + "Z").getTime();
}
