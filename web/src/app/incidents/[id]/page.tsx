"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import SignalChart from "@/components/SignalChart";
import { fmtDuration, fmtNum, fmtUtc, fmtUtcTime } from "@/lib/format";
import { SIGNALS, type Incident } from "@/lib/signals";

type Detail = {
  incident: Incident;
  points: Record<string, number>[];
  prev_id: number | null;
  next_id: number | null;
};

type Peaks = {
  baseline?: Record<string, number>;
  min_speed?: number;
  max_vibration?: number;
  max_current?: number;
  max_torque?: number;
  max_force?: number;
};

export default function IncidentPage() {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/incidents/${id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status === 404 ? "Incident not found" : `API returned ${r.status}`))))
      .then(setDetail)
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (!detail || String(detail.incident.id) !== id) return <p className="text-sm text-muted">Loading…</p>;

  const inc = detail.incident;
  const start = new Date(inc.started_at).getTime();
  const end = inc.ended_at ? new Date(inc.ended_at).getTime() : start;
  const peaks = (inc.peak_values ?? {}) as Peaks;
  const base = peaks.baseline ?? {};
  const peakRows = [
    { label: "Motor speed (min)", key: "motor_speed", value: peaks.min_speed, unit: "rpm" },
    { label: "Vibration (max)", key: "vibration", value: peaks.max_vibration, unit: "mm/s" },
    { label: "Motor current (max)", key: "motor_current", value: peaks.max_current, unit: "A" },
    { label: "Torque (max)", key: "torque", value: peaks.max_torque, unit: "kN·m" },
    { label: "Rolling force (max)", key: "rolling_force", value: peaks.max_force, unit: "kN" },
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/incidents" className="text-sm text-muted hover:text-foreground">
          ← All incidents
        </Link>
        <div className="ml-auto flex gap-2 text-sm">
          {detail.prev_id && (
            <Link href={`/incidents/${detail.prev_id}`} className="px-3 py-1 rounded-md border border-line hover:bg-line">
              Previous
            </Link>
          )}
          {detail.next_id && (
            <Link href={`/incidents/${detail.next_id}`} className="px-3 py-1 rounded-md border border-line hover:bg-line">
              Next
            </Link>
          )}
        </div>
      </div>

      <div className="bg-panel border border-red-500/40 rounded-xl p-4 space-y-2">
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <span className="font-semibold text-red-400">Incident #{inc.id}</span>
          <span>{inc.mill_id}</span>
          <span className="font-mono">{fmtUtc(inc.started_at, true)} UTC</span>
          <span className="text-muted">Duration {fmtDuration(inc.started_at, inc.ended_at)}</span>
        </div>
        <p>{inc.reason}</p>
        <p className="text-sm text-muted">Affected signals: {inc.affected_signals.join(", ")}</p>
      </div>

      <div className="grid lg:grid-cols-[1fr_300px] gap-5">
        <div className="grid md:grid-cols-2 gap-3">
          {SIGNALS.map((s) => (
            <SignalChart
              key={s.key}
              data={detail.points}
              valueKey={s.key}
              color={s.color}
              label={s.label + (inc.affected_signals.includes(s.key) ? " (affected)" : "")}
              unit={s.unit}
              shades={[{ from: start, to: end }]}
              formatTime={(ms) => fmtUtcTime(ms)}
            />
          ))}
        </div>
        <aside className="bg-panel border border-line rounded-xl p-4 h-fit">
          <h2 className="font-medium mb-3">Peaks vs normal</h2>
          <table className="w-full text-sm">
            <thead className="text-xs text-muted">
              <tr>
                <th className="text-left font-normal"></th>
                <th className="text-right font-normal">Normal</th>
                <th className="text-right font-normal">Peak</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {peakRows.map((r) => (
                <tr key={r.key} className="border-t border-line">
                  <td className="py-1.5 font-sans text-xs">{r.label}</td>
                  <td className="text-right">{fmtNum(base[r.key])}</td>
                  <td className="text-right text-red-300">{fmtNum(r.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-muted mt-3">
            Charts show 30 s either side of the incident, from the stored snapshot (100 ms averages). The red band is
            the incident from open to close.
          </p>
        </aside>
      </div>
    </div>
  );
}
