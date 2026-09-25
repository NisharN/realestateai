"use client";

import Link from "next/link";
import { Clock, MapPin } from "lucide-react";
import type { BrokerLeadSummary } from "@/lib/api";
import { bandTone, formatBudget, relativeTime, STAGE_LABELS } from "@/lib/broker-format";
import { EmptyState, Section, Skeleton } from "@/components/ui/page";

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0 || name === "Unknown") return "?";
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
}

export function LeadCard({ lead, children }: { lead: BrokerLeadSummary; children?: React.ReactNode }) {
  const profile = [lead.purpose, lead.property_type].filter(Boolean).join(" · ");
  return (
    <div className="group min-w-0 rounded-2xl border border-border bg-card p-4 shadow-card transition hover:shadow-card-hover hover:border-brand/20">
      <div className="flex items-start gap-3">
        <div className="h-9 w-9 shrink-0 rounded-full bg-brand/10 text-brand flex items-center justify-center text-xs font-semibold">{initials(lead.name)}</div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <Link href={`/broker/leads/${lead.id}`} className="truncate font-semibold text-foreground hover:text-brand">
              {lead.name}
            </Link>
            <span className={`ui-badge shrink-0 ${bandTone(lead.band)}`}>
              {lead.band ?? "unscored"}
              {lead.score ? <span className="tabular">· {lead.score}</span> : null}
            </span>
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground capitalize">{profile || "Profile incomplete"}</p>
          {lead.areas.length > 0 && (
            <p className="mt-1 flex items-center gap-1 truncate text-xs text-muted-foreground">
              <MapPin className="h-3 w-3 shrink-0" />
              <span className="truncate">{lead.areas.join(", ")}</span>
            </p>
          )}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="tabular font-medium text-foreground">{formatBudget(lead)}</span>
        <span className="ui-badge bg-muted text-muted-foreground">{STAGE_LABELS[lead.stage] ?? lead.stage}</span>
        {lead.timeline && <span>Timeline: {lead.timeline.replace(/_/g, " ")}</span>}
        <span className="uppercase">{lead.language}</span>
        <span className="ms-auto flex items-center gap-1 text-muted-foreground/70">
          <Clock className="h-3 w-3" />
          {relativeTime(lead.updated_at ?? lead.created_at)}
        </span>
      </div>
      {children && <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border/70 pt-3">{children}</div>}
    </div>
  );
}

export function Panel({ title, count, children, empty }: { title: string; count?: number; children: React.ReactNode; empty?: string }) {
  const isEmpty = Array.isArray(children) ? children.length === 0 : !children;
  return (
    <Section title={title} count={count}>
      {isEmpty ? <EmptyState title={empty ?? "Nothing here."} /> : <div className="grid grid-cols-1 gap-3">{children}</div>}
    </Section>
  );
}

export function StatusBanner({ error, loading }: { error: string | null; loading: boolean }) {
  if (error)
    return (
      <p role="alert" className="rounded-xl border border-danger/20 bg-danger-soft p-4 text-sm text-danger">
        {error}
      </p>
    );
  if (loading)
    return (
      <div role="status" aria-label="Loading" className="grid gap-3 md:grid-cols-2">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
    );
  return null;
}
