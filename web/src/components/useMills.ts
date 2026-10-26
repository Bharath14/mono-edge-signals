"use client";

import { useEffect, useState } from "react";

export type Mill = { mill_id: string; first_ts: string; last_ts: string };

export function useMills() {
  const [mills, setMills] = useState<Mill[]>([]);
  useEffect(() => {
    fetch("/api/mills")
      .then((r) => r.json())
      .then((d) => setMills(d.mills ?? []))
      .catch(() => setMills([]));
  }, []);
  return mills;
}
