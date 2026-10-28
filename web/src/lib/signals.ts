// Signal metadata shared by the API routes and the UI. Column names match
// processed_readings; `rollup` is the prefix used in historical_rollups.

export const SIGNALS = [
  { key: "motor_speed", label: "Motor speed", unit: "rpm", rollup: "speed", color: "#38bdf8" },
  { key: "motor_current", label: "Motor current", unit: "A", rollup: "current", color: "#a78bfa" },
  { key: "torque", label: "Torque", unit: "kN·m", rollup: "torque", color: "#f472b6" },
  { key: "rolling_force", label: "Rolling force", unit: "kN", rollup: "force", color: "#fb923c" },
  { key: "vibration", label: "Vibration", unit: "mm/s", rollup: "vib", color: "#facc15" },
  { key: "temperature", label: "Temperature", unit: "°C", rollup: "temp", color: "#4ade80" },
] as const;

export type SignalKey = (typeof SIGNALS)[number]["key"];
export type Signal = (typeof SIGNALS)[number];

export const SIGNAL_KEYS = SIGNALS.map((s) => s.key) as SignalKey[];

export function getSignal(key: string | null): Signal | undefined {
  return SIGNALS.find((s) => s.key === key);
}

export const DEFAULT_MILL = "RM-01";

// Shortcuts into each mill's seed loop (seconds from loop start). They mirror
// the event schedules in simulator/config.py.
export const MILL_PRESETS: Record<string, { label: string; from: number; to: number }[]> = {
  "RM-01": [
    { label: "Whole loop (10 min)", from: 0, to: 600 },
    { label: "Cobble at 0:30", from: 20, to: 50 },
    { label: "Load change 2:00 to 3:45", from: 120, to: 225 },
    { label: "Speed step down 6:50 to 8:20", from: 410, to: 500 },
  ],
  "RM-02": [
    { label: "Whole loop (10 min)", from: 0, to: 600 },
    { label: "Cobble at 1:10", from: 60, to: 90 },
    { label: "Speed step up 1:35 to 3:30, cobble at 2:30", from: 95, to: 210 },
    { label: "Load change 5:20 to 6:55", from: 320, to: 415 },
  ],
};

// The seed loop is stored at a fixed synthetic date (see simulator/config.py).
// The hosted demo replays it: every viewer sees the same position because the
// position is computed from the wall clock, with no server state.
export const LOOP_START_MS = Date.UTC(2026, 0, 1, 0, 0, 0);
export const LOOP_MS = 600_000;
export const LOOP_END_MS = LOOP_START_MS + LOOP_MS;

// Newest stored row younger than this means a simulator is streaming: show
// real live data instead of the replay.
export const LIVE_THRESHOLD_MS = 10_000;

export function replayNow(nowMs: number): number {
  return LOOP_START_MS + (nowMs % LOOP_MS);
}

export type Incident = {
  id: number;
  mill_id: string;
  started_at: string;
  ended_at: string | null;
  affected_signals: string[];
  reason: string;
  peak_values: Record<string, unknown> | null;
};
