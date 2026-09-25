"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { brokerApi, type BrokerPipeline } from "@/lib/api";
import { STAGE_LABELS } from "@/lib/broker-format";
import { useBrokerScope } from "@/lib/use-broker-scope";
import { LeadCard, StatusBanner } from "@/components/broker/lead-card";

export default function PipelinePage() {
  const scope = useBrokerScope();
  const [data, setData] = useState<BrokerPipeline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState<string>("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!scope.ready) return;
    brokerApi.pipeline(scope.brokerId).then((r) => {
      if (r.error) setError(r.error);
      else {
        setError(null);
        setData(r.data ?? null);
      }
    });
  }, [scope.ready, scope.brokerId]);

  const q = query.trim().toLowerCase();
  const stages = (data?.stages ?? [])
    .filter((s) => !stageFilter || s.stage === stageFilter)
    .map((s) => ({
      ...s,
      leads: q ? s.leads.filter((l) => `${l.name} ${l.phone ?? ""} ${l.areas.join(" ")}`.toLowerCase().includes(q)) : s.leads,
    }));

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-8">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold">Pipeline</h1>
            <p className="mt-1 text-slate-600">Every lead by stage{scope.brokerId ? ` for broker ${scope.brokerId}` : ""}.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Link href="/broker" className="rounded-xl border bg-white px-4 py-2 font-medium hover:bg-slate-100">
              Today
            </Link>
            <input
              aria-label="Search leads"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name, phone, area"
              className="rounded-xl border px-3 py-2"
            />
            <select aria-label="Stage" value={stageFilter} onChange={(e) => setStageFilter(e.target.value)} className="rounded-xl border px-3 py-2">
              <option value="">All stages</option>
              {(data?.stages ?? []).map((s) => (
                <option key={s.stage} value={s.stage}>
                  {STAGE_LABELS[s.stage] ?? s.stage} ({s.count})
                </option>
              ))}
            </select>
          </div>
        </header>

        <div className="mt-4">
          <StatusBanner error={error} loading={!data && !error} />
        </div>

        {data && (
          <div className="mt-6 flex gap-4 overflow-x-auto pb-4">
            {stages.map((s) => (
              <section key={s.stage} className="w-72 shrink-0 rounded-2xl border bg-slate-100/70 p-3">
                <h2 className="mb-3 flex items-center justify-between text-sm font-semibold text-slate-700">
                  {STAGE_LABELS[s.stage] ?? s.stage}
                  <span className="rounded-full bg-white px-2 py-0.5 text-xs">{s.count}</span>
                </h2>
                <div className="grid gap-3">
                  {s.leads.length === 0 ? (
                    <p className="text-xs text-slate-500">Empty</p>
                  ) : (
                    s.leads.map((lead) => <LeadCard key={lead.id} lead={lead} />)
                  )}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
