"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import SignalChart, { type Shade } from "@/components/SignalChart";
import SignalPicker from "@/components/SignalPicker";
import { useMills } from "@/components/useMills";
import { fmtLocalTime, fmtNum } from "@/lib/format";
import { DEFAULT_MILL, LOOP_START_MS, SIGNALS, SIGNAL_KEYS, getSignal, type SignalKey } from "@/lib/signals";

type Alert = {
  id: number;
  started_at: string;
  ended_at: string | null;
  affected_signals: string[];
  reason: string;
  fired_at: number;
  open: boolean;
};

type LiveData = {
  mode: "LIVE" | "REPLAY";
  serverNow: number;
  virtualNow: string;
  windowS: number;
  status: "RUNNING" | "INCIDENT" | "NO DATA";
  latest: Record<string, number> | null;
  points: Record<string, number>[];
  alerts: Alert[];
};

const POLL_MS = 1000;

export default function LivePage() {
  const mills = useMills();
  const [mill, setMill] = useState(DEFAULT_MILL);
  const [windowS, setWindowS] = useState(60);
  const [selected, setSelected] = useState<SignalKey[]>(SIGNAL_KEYS);
  const [data, setData] = useState<LiveData | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll once a second. Polling suits short-lived serverless functions better
  // than a held-open stream. The next poll is scheduled after the previous
  // one finishes, so slow responses never pile up.
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const res = await fetch(`/api/live?mill=${encodeURIComponent(mill)}&window=${windowS}`, { cache: "no-store" });
        if (!res.ok) throw new Error(`API returned ${res.status}`);
        const json = await res.json();
        if (!stopped) {
          setData(json);
          setError(null);
        }
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : "request failed");
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS);
    }
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [mill, windowS]);

  const domain: [number, number] | undefined = data
    ? [data.serverNow - data.windowS * 1000, data.serverNow]
    : undefined;

  // Incident periods mapped onto the live time axis.
  const shades: Shade[] = (data?.alerts ?? []).map((a) => ({
    from: a.fired_at,
    to: a.open
      ? data!.serverNow
      : a.fired_at + (new Date(a.ended_at!).getTime() - new Date(a.started_at).getTime()),
  }));

  const openAlert = data?.alerts.find((a) => a.open);
  const loopPos = data ? (new Date(data.virtualNow).getTime() - LOOP_START_MS) / 1000 : 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold mr-2">Live monitoring</h1>
        <select
          value={mill}
          onChange={(e) => setMill(e.target.value)}
          className="bg-panel border border-line rounded-md px-2 py-1.5 text-sm"
        >
          {(mills.length ? mills.map((m) => m.mill_id) : [DEFAULT_MILL]).map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
        <select
          value={windowS}
          onChange={(e) => setWindowS(Number(e.target.value))}
          className="bg-panel border border-line rounded-md px-2 py-1.5 text-sm"
        >
          <option value={30}>Last 30 s</option>
          <option value={60}>Last 60 s</option>
          <option value={120}>Last 2 min</option>
        </select>
        {data && <ModeBadge mode={data.mode} loopPos={loopPos} />}
        {data && <StatusBadge status={data.status} />}
        {error && <span className="text-sm text-red-400">Connection problem: {error}</span>}
      </div>

      {openAlert && (
        <div className="rounded-xl border border-red-500/60 bg-red-500/10 px-4 py-3 text-sm">
          <span className="font-semibold text-red-400 mr-2">INCIDENT</span>
          {openAlert.reason}{" "}
          <Link href={`/incidents/${openAlert.id}`} className="underline text-red-300">
            View incident
          </Link>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {SIGNALS.map((s) => (
          <div key={s.key} className="bg-panel border border-line rounded-xl px-3 py-2">
            <div className="text-xs text-muted">{s.label}</div>
            <div className="text-lg font-mono" style={{ color: s.color }}>
              {fmtNum(data?.latest?.[s.key])} <span className="text-xs text-muted">{s.unit}</span>
            </div>
          </div>
        ))}
      </div>

      <SignalPicker selected={selected} onChange={setSelected} />

      <div className="grid lg:grid-cols-[1fr_320px] gap-5 items-start">
        <div className="grid md:grid-cols-2 gap-3 content-start">
          {selected.map((key) => {
            const s = getSignal(key)!;
            return (
              <SignalChart
                key={key}
                data={data?.points ?? []}
                valueKey={key}
                color={s.color}
                label={s.label}
                unit={s.unit}
                domain={domain}
                shades={shades}
                formatTime={fmtLocalTime}
              />
            );
          })}
          {!selected.length && <p className="text-sm text-muted">Pick at least one signal.</p>}
        </div>

        <aside className="bg-panel border border-line rounded-xl p-4 h-fit">
          <h2 className="font-medium mb-1">Alerts</h2>
          <p className="text-xs text-muted mb-3">
            {data?.mode === "REPLAY" ? "Fired so far in this pass of the demo loop." : "Last hour."}
          </p>
          {!data?.alerts.length && <p className="text-sm text-muted">No alerts.</p>}
          <ul className="space-y-3 max-h-[560px] overflow-y-auto pr-1">
            {data?.alerts.map((a) => (
              <li key={a.id} className="text-sm border-l-2 border-red-500 pl-3">
                <div className="flex justify-between text-xs text-muted">
                  <span>{fmtLocalTime(a.fired_at)}</span>
                  <span>{a.open ? <span className="text-red-400">ongoing</span> : "closed"}</span>
                </div>
                <div className="mt-0.5">{a.reason}</div>
                <div className="text-xs text-muted mt-0.5">Signals: {a.affected_signals.join(", ")}</div>
                <Link href={`/incidents/${a.id}`} className="text-xs text-sky-400 hover:underline">
                  Explore
                </Link>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
}

function ModeBadge({ mode, loopPos }: { mode: "LIVE" | "REPLAY"; loopPos: number }) {
  if (mode === "LIVE") {
    return <span className="text-xs font-semibold px-2 py-1 rounded bg-emerald-500/20 text-emerald-400">LIVE</span>;
  }
  const m = Math.floor(loopPos / 60);
  const s = Math.floor(loopPos % 60).toString().padStart(2, "0");
  return (
    <span
      className="text-xs font-semibold px-2 py-1 rounded bg-sky-500/20 text-sky-300"
      title="No simulator is streaming, so the stored 10 minute seed loop is replayed on the wall clock."
    >
      REPLAY (demo loop {m}:{s} / 10:00)
    </span>
  );
}

function StatusBadge({ status }: { status: LiveData["status"] }) {
  const style =
    status === "INCIDENT"
      ? "bg-red-500/20 text-red-400"
      : status === "RUNNING"
        ? "bg-emerald-500/10 text-emerald-300"
        : "bg-line text-muted";
  return <span className={`text-xs font-semibold px-2 py-1 rounded ${style}`}>{status}</span>;
}
