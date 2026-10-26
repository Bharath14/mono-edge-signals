"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fmtDuration, fmtUtc } from "@/lib/format";
import type { Incident } from "@/lib/signals";

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/incidents")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API returned ${r.status}`))))
      .then((d) => setIncidents(d.incidents))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Incident history</h1>
        <p className="text-sm text-muted">Every stored alert, newest first. Times in UTC.</p>
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
      {incidents && !incidents.length && <p className="text-sm text-muted">No incidents stored.</p>}
      {incidents && incidents.length > 0 && (
        <div className="bg-panel border border-line rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted">
              <tr className="text-left">
                <th className="font-normal px-4 py-2">Started</th>
                <th className="font-normal px-4 py-2">Mill</th>
                <th className="font-normal px-4 py-2">Duration</th>
                <th className="font-normal px-4 py-2">Affected signals</th>
                <th className="font-normal px-4 py-2">Reason</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((i) => (
                <tr key={i.id} className="border-t border-line align-top">
                  <td className="px-4 py-2 font-mono text-xs whitespace-nowrap">{fmtUtc(i.started_at, true)}</td>
                  <td className="px-4 py-2">{i.mill_id}</td>
                  <td className="px-4 py-2 whitespace-nowrap">{fmtDuration(i.started_at, i.ended_at)}</td>
                  <td className="px-4 py-2 text-xs text-muted">{i.affected_signals.join(", ")}</td>
                  <td className="px-4 py-2">{i.reason}</td>
                  <td className="px-4 py-2">
                    <Link href={`/incidents/${i.id}`} className="text-sky-400 hover:underline whitespace-nowrap">
                      Explore
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
