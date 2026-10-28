"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import SignalChart from "@/components/SignalChart";
import SignalPicker from "@/components/SignalPicker";
import { useMills } from "@/components/useMills";
import { fmtDuration, fmtNum, fmtUtc, fmtUtcTime, fromUtcInput, toUtcInput } from "@/lib/format";
import { DEFAULT_MILL, LOOP_START_MS, MILL_PRESETS, getSignal, type SignalKey } from "@/lib/signals";

type Stats = { points: number; avg: number; min: number; max: number } | null;
type HistoryData = {
  source: string;
  points: { t: number; avg: number | null; min: number | null; max: number | null }[];
  incidents: { id: number; started_at: string; ended_at: string | null; affected_signals: string[]; reason: string }[];
  stats: { normal: Stats; abnormal: Stats };
};


export default function HistoryPage() {
  const mills = useMills();
  const [mill, setMill] = useState(DEFAULT_MILL);
  const [signal, setSignal] = useState<SignalKey>("motor_speed");
  const [from, setFrom] = useState(toUtcInput(LOOP_START_MS));
  const [to, setTo] = useState(toUtcInput(LOOP_START_MS + 600_000));
  // The applied query. Mill and signal apply at once, time edits on "Load".
  const [query, setQuery] = useState({ mill, signal, from, to });
  const [result, setResult] = useState<{ query: typeof query; data: HistoryData | null; error: string | null } | null>(
    null,
  );

  const millInfo = mills.find((m) => m.mill_id === mill);
  const base = millInfo ? new Date(millInfo.first_ts).getTime() : LOOP_START_MS;

  useEffect(() => {
    let stale = false;
    const q = new URLSearchParams({
      mill: query.mill,
      signal: query.signal,
      from: new Date(fromUtcInput(query.from)).toISOString(),
      to: new Date(fromUtcInput(query.to)).toISOString(),
    });
    fetch(`/api/history?${q}`)
      .then(async (res) => {
        const json = await res.json();
        if (!res.ok) throw new Error(json.error ?? `API returned ${res.status}`);
        if (!stale) setResult({ query, data: json, error: null });
      })
      .catch((e) => {
        if (!stale) setResult({ query, data: null, error: e instanceof Error ? e.message : "request failed" });
      });
    return () => {
      stale = true;
    };
  }, [query]);

  const loading = result?.query !== query;
  const data = result?.data ?? null;
  const error = result?.error ?? null;

  const s = getSignal(query.signal)!;
  const spanMs = fromUtcInput(query.to) - fromUtcInput(query.from);
  const fmtAxis = (ms: number) => fmtUtcTime(ms, spanMs <= 60_000);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="text-xl font-semibold mr-2">Historical analytics</h1>
        <select
          value={mill}
          onChange={(e) => {
            setMill(e.target.value);
            setQuery({ ...query, mill: e.target.value });
          }}
          className="bg-panel border border-line rounded-md px-2 py-1.5 text-sm"
        >
          {(mills.length ? mills.map((m) => m.mill_id) : [DEFAULT_MILL]).map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
        <label className="text-xs text-muted">
          From (UTC)
          <input
            type="datetime-local"
            step={1}
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="block mt-1 bg-panel border border-line rounded-md px-2 py-1 text-sm text-foreground"
          />
        </label>
        <label className="text-xs text-muted">
          To (UTC)
          <input
            type="datetime-local"
            step={1}
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="block mt-1 bg-panel border border-line rounded-md px-2 py-1 text-sm text-foreground"
          />
        </label>
        <button onClick={() => setQuery({ mill, signal, from, to })} className="rounded-md bg-sky-600 hover:bg-sky-500 px-3 py-1.5 text-sm font-medium">
          {loading ? "Loading…" : "Load"}
        </button>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        <span className="text-muted py-1">Seed loop shortcuts:</span>
        {(MILL_PRESETS[mill] ?? MILL_PRESETS[DEFAULT_MILL]).map((p) => (
          <button
            key={p.label}
            onClick={() => {
              const f = toUtcInput(base + p.from * 1000);
              const t = toUtcInput(base + p.to * 1000);
              setFrom(f);
              setTo(t);
              setQuery({ mill, signal, from: f, to: t });
            }}
            className="px-2.5 py-1 rounded-full border border-line text-muted hover:text-foreground"
          >
            {p.label}
          </button>
        ))}
        {millInfo && (
          <span className="text-muted py-1 ml-auto">
            Stored data: {fmtUtc(millInfo.first_ts)} to {fmtUtc(millInfo.last_ts)} UTC
          </span>
        )}
      </div>

      <SignalPicker selected={[signal]} onChange={(k) => {
          setSignal(k[0]);
          setQuery({ ...query, signal: k[0] });
        }} multiple={false} />

      {error && <p className="text-sm text-red-400">{error}</p>}

      {data && (
        <>
          <SignalChart
            data={data.points}
            valueKey="avg"
            minKey="min"
            maxKey="max"
            color={s.color}
            label={`${s.label} (line avg, band min to max)`}
            unit={s.unit}
            height={320}
            shades={data.incidents.map((i) => ({
              from: new Date(i.started_at).getTime(),
              to: new Date(i.ended_at ?? i.started_at).getTime(),
            }))}
            formatTime={fmtAxis}
          />
          <p className="text-xs text-muted">
            Source: {data.source}, {data.points.length} points. Red bands are detected incidents.
          </p>

          <div className="grid md:grid-cols-2 gap-5">
            <div className="bg-panel border border-line rounded-xl p-4">
              <h2 className="font-medium mb-3">Normal vs abnormal</h2>
              <table className="w-full text-sm">
                <thead className="text-muted text-xs">
                  <tr>
                    <th className="text-left font-normal"></th>
                    <th className="text-right font-normal">Avg</th>
                    <th className="text-right font-normal">Min</th>
                    <th className="text-right font-normal">Max</th>
                    <th className="text-right font-normal">Share of time</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {(["normal", "abnormal"] as const).map((k) => {
                    const st = data.stats[k];
                    const total = (data.stats.normal?.points ?? 0) + (data.stats.abnormal?.points ?? 0);
                    return (
                      <tr key={k} className="border-t border-line">
                        <td className={`py-1.5 font-sans ${k === "abnormal" ? "text-red-400" : ""}`}>
                          {k === "normal" ? "Normal" : "During incidents"}
                        </td>
                        <td className="text-right">{fmtNum(st?.avg)}</td>
                        <td className="text-right">{fmtNum(st?.min)}</td>
                        <td className="text-right">{fmtNum(st?.max)}</td>
                        <td className="text-right">{total ? `${(((st?.points ?? 0) / total) * 100).toFixed(1)}%` : "–"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="text-xs text-muted mt-2">Values in {s.unit}. Min and max come from full resolution data.</p>
            </div>

            <div className="bg-panel border border-line rounded-xl p-4">
              <h2 className="font-medium mb-3">Incidents in range ({data.incidents.length})</h2>
              {!data.incidents.length && <p className="text-sm text-muted">None. This range is normal operation.</p>}
              <ul className="space-y-2 text-sm max-h-64 overflow-auto">
                {data.incidents.map((i) => (
                  <li key={i.id} className="flex justify-between gap-3">
                    <span className="font-mono text-xs">{fmtUtc(i.started_at)}</span>
                    <span className="text-muted text-xs">{fmtDuration(i.started_at, i.ended_at)}</span>
                    <Link href={`/incidents/${i.id}`} className="text-sky-400 text-xs hover:underline">
                      Explore
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
