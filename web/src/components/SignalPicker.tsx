"use client";

import { SIGNALS, type SignalKey } from "@/lib/signals";

type Props = {
  selected: SignalKey[];
  onChange: (keys: SignalKey[]) => void;
  multiple?: boolean;
};

export default function SignalPicker({ selected, onChange, multiple = true }: Props) {
  function toggle(key: SignalKey) {
    if (!multiple) return onChange([key]);
    onChange(selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]);
  }
  return (
    <div className="flex flex-wrap gap-2">
      {SIGNALS.map((s) => {
        const on = selected.includes(s.key);
        return (
          <button
            key={s.key}
            onClick={() => toggle(s.key)}
            className={`text-xs px-2.5 py-1 rounded-full border ${on ? "border-transparent text-background font-medium" : "border-line text-muted hover:text-foreground"}`}
            style={on ? { background: s.color } : undefined}
          >
            {s.label}
          </button>
        );
      })}
    </div>
  );
}
