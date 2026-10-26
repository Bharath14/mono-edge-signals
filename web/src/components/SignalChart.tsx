"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type Shade = { from: number; to: number; label?: string };

type Props = {
  data: Record<string, number | null>[];
  valueKey: string;
  // Optional min/max keys: drawn as a band behind the line so spikes that
  // the average hides are still visible.
  minKey?: string;
  maxKey?: string;
  color: string;
  label: string;
  unit: string;
  height?: number;
  domain?: [number, number];
  shades?: Shade[];
  markers?: number[];
  formatTime: (ms: number) => string;
};

export default function SignalChart({
  data,
  valueKey,
  minKey,
  maxKey,
  color,
  label,
  unit,
  height = 180,
  domain,
  shades = [],
  markers = [],
  formatTime,
}: Props) {
  return (
    <div className="bg-panel border border-line rounded-xl p-3">
      <div className="flex items-baseline justify-between px-1 mb-1">
        <span className="text-sm font-medium" style={{ color }}>
          {label}
        </span>
        <span className="text-xs text-muted">{unit}</span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#223041" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={domain ?? ["dataMin", "dataMax"]}
            allowDataOverflow
            tickFormatter={formatTime}
            stroke="#8796a8"
            fontSize={11}
            minTickGap={40}
          />
          <YAxis stroke="#8796a8" fontSize={11} width={48} domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{ background: "#121a23", border: "1px solid #223041", fontSize: 12 }}
            labelFormatter={(v) => formatTime(Number(v))}
            formatter={(v) => (Array.isArray(v) ? v.map((x) => Number(x).toFixed(2)).join(" to ") : Number(v).toFixed(2))}
          />
          {shades.map((s, i) => (
            <ReferenceArea key={i} x1={s.from} x2={s.to} fill="#ef4444" fillOpacity={0.15} stroke="none" ifOverflow="hidden" />
          ))}
          {markers.map((m, i) => (
            <ReferenceLine key={i} x={m} stroke="#ef4444" strokeDasharray="4 2" ifOverflow="hidden" />
          ))}
          {minKey && maxKey && (
            <Area
              dataKey={(d) => [d[minKey], d[maxKey]]}
              name="min to max"
              stroke="none"
              fill={color}
              fillOpacity={0.35}
              isAnimationActive={false}
            />
          )}
          <Line
            dataKey={valueKey}
            name={minKey ? "avg" : label}
            stroke={color}
            dot={false}
            strokeWidth={1.5}
            isAnimationActive={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
