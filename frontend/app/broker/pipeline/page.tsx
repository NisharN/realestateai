"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { KanbanSquare, List, Search } from "lucide-react";
import { brokerApi, type BrokerPipeline } from "@/lib/api";
import { bandTone, formatBudget, relativeTime, STAGE_LABELS } from "@/lib/broker-format";
import { useBrokerScope } from "@/lib/use-broker-scope";
import { LeadCard, StatusBanner } from "@/components/broker/lead-card";
import { EmptyState, Page, PageHeader } from "@/components/ui/page";

const STAGE_ACCENT: Record<string, string> = {
  new: "bg-brand",
  qualifying: "bg-brand-2",
  qualified: "bg-gold",
  handed_off: "bg-warning",
  viewing_booked: "bg-success",
  offer: "bg-success",
  closed: "bg-success",
  lost: "bg-danger",
  opted_out: "bg-muted-foreground",
};

export default function PipelinePage() {
  const scope = useBrokerScope();
  const [data, setData] = useState<BrokerPipeline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState<string>("");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"board" | "table">("board");

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
  const total = (data?.stages ?? []).reduce((n, s) => n + s.count, 0);

  return (
    <Page width="max-w-[1600px]">
      <PageHeader
        kicker="Broker workspace"
        title="Pipeline"
        description={
          <>
            <span className="tabular">{total.toLocaleString("en-US")}</span> leads by stage
            {scope.brokerId ? ` for broker ${scope.brokerId}` : ""}. Each column shows the most recent leads.
          </>
        }
        actions={
          <>
            <Link href="/broker" className="ui-btn-secondary">
              Today
            </Link>
            <div className="inline-flex rounded-xl border border-border bg-card p-0.5">
              <button
                type="button"
                aria-pressed={view === "board"}
                onClick={() => setView("board")}
                className={`ui-btn ui-btn-sm rounded-lg ${view === "board" ? "bg-brand text-white" : "text-muted-foreground"}`}
              >
                <KanbanSquare className="h-3.5 w-3.5" /> Board
              </button>
              <button
                type="button"
                aria-pressed={view === "table"}
                onClick={() => setView("table")}
                className={`ui-btn ui-btn-sm rounded-lg ${view === "table" ? "bg-brand text-white" : "text-muted-foreground"}`}
              >
                <List className="h-3.5 w-3.5" /> Table
              </button>
            </div>
          </>
        }
      />

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <label className="relative">
          <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            aria-label="Search leads"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search name, phone, area"
            className="ui-input w-72 ps-9"
          />
        </label>
        <select aria-label="Stage" value={stageFilter} onChange={(e) => setStageFilter(e.target.value)} className="ui-input">
          <option value="">All stages</option>
          {(data?.stages ?? []).map((s) => (
            <option key={s.stage} value={s.stage}>
              {STAGE_LABELS[s.stage] ?? s.stage} ({s.count.toLocaleString("en-US")})
            </option>
          ))}
        </select>
      </div>

      <div className="mt-4">
        <StatusBanner error={error} loading={!data && !error} />
      </div>

      {data && view === "board" && (
        <div className="mt-6 flex gap-4 overflow-x-auto pb-4">
          {stages.map((s) => (
            <section key={s.stage} className="flex w-80 shrink-0 flex-col rounded-2xl bg-muted/60 p-3">
              <h2 className="mb-3 flex items-center gap-2 px-1 text-sm font-semibold text-foreground">
                <span className={`h-2 w-2 rounded-full ${STAGE_ACCENT[s.stage] ?? "bg-border"}`} aria-hidden />
                {STAGE_LABELS[s.stage] ?? s.stage}
                <span className="ms-auto ui-badge bg-card text-muted-foreground tabular">{s.count.toLocaleString("en-US")}</span>
              </h2>
              <div className="grid grid-cols-1 gap-3">
                {s.leads.length === 0 ? (
                  <EmptyState title="No leads" body={q ? "Nothing matches your search." : undefined} />
                ) : (
                  s.leads.map((lead) => <LeadCard key={lead.id} lead={lead} />)
                )}
              </div>
            </section>
          ))}
        </div>
      )}

      {data && view === "table" && (
        <div className="ui-card mt-6 overflow-x-auto">
          <table className="ui-table">
            <thead>
              <tr>
                <th>Lead</th>
                <th>Stage</th>
                <th>Brief</th>
                <th>Budget</th>
                <th>Score</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {stages.flatMap((s) =>
                s.leads.map((lead) => (
                  <tr key={lead.id}>
                    <td>
                      <Link href={`/broker/leads/${lead.id}`} className="font-medium hover:text-brand">
                        {lead.name}
                      </Link>
                      <p className="text-xs text-muted-foreground">{lead.phone ?? "—"}</p>
                    </td>
                    <td>
                      <span className="ui-badge bg-muted text-muted-foreground">{STAGE_LABELS[s.stage] ?? s.stage}</span>
                    </td>
                    <td className="capitalize text-muted-foreground">
                      {[lead.purpose, lead.property_type, lead.areas.join(", ")].filter(Boolean).join(" · ") || "—"}
                    </td>
                    <td className="tabular whitespace-nowrap">{formatBudget(lead)}</td>
                    <td>
                      <span className={`ui-badge ${bandTone(lead.band)}`}>
                        {lead.band ?? "—"}
                        {lead.score ? ` · ${lead.score}` : ""}
                      </span>
                    </td>
                    <td className="whitespace-nowrap text-muted-foreground">{relativeTime(lead.updated_at ?? lead.created_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          {stages.every((s) => s.leads.length === 0) && (
            <div className="p-6">
              <EmptyState title="No leads match" />
            </div>
          )}
        </div>
      )}
    </Page>
  );
}
