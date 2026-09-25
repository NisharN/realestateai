"use client";

import Link from "next/link";
import type { BrokerLeadSummary } from "@/lib/api";
import { bandTone, formatBudget, relativeTime, STAGE_LABELS } from "@/lib/broker-format";

export function LeadCard({ lead, children }: { lead: BrokerLeadSummary; children?: React.ReactNode }) {
  return (
    <div className="rounded-xl border bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/broker/leads/${lead.id}`} className="font-semibold text-slate-900 hover:underline">
            {lead.name}
          </Link>
          <p className="mt-0.5 truncate text-xs text-slate-500">
            {[lead.purpose, lead.property_type, lead.areas.join(", ")].filter(Boolean).join(" · ") || "Profile incomplete"}
          </p>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${bandTone(lead.band)}`}>
          {lead.band ?? "unscored"} {lead.score ? `· ${lead.score}` : ""}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
        <span>{formatBudget(lead)}</span>
        <span>{STAGE_LABELS[lead.stage] ?? lead.stage}</span>
        {lead.timeline && <span>Timeline: {lead.timeline}</span>}
        <span className="uppercase">{lead.language}</span>
        <span className="ml-auto text-slate-400">{relativeTime(lead.updated_at ?? lead.created_at)}</span>
      </div>
      {children && <div className="mt-3 flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

export function Panel({ title, count, children, empty }: { title: string; count?: number; children: React.ReactNode; empty?: string }) {
  const isEmpty = Array.isArray(children) ? children.length === 0 : !children;
  return (
    <section className="rounded-2xl border bg-slate-50/60 p-4">
      <h2 className="mb-3 flex items-center justify-between text-sm font-semibold uppercase tracking-wide text-slate-600">
        {title}
        {count != null && <span className="rounded-full bg-white px-2 py-0.5 text-xs text-slate-700">{count}</span>}
      </h2>
      {isEmpty ? <p className="text-sm text-slate-500">{empty ?? "Nothing here."}</p> : <div className="grid gap-3">{children}</div>}
    </section>
  );
}

export function StatusBanner({ error, loading }: { error: string | null; loading: boolean }) {
  if (error) return <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>;
  if (loading) return <p role="status" className="text-sm text-slate-500">Loading…</p>;
  return null;
}
