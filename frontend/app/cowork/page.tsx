"use client";

/**
 * Co-work — one operational surface for everything that runs alongside the
 * team: integrations, scheduled jobs, task automations, run history and the
 * audit trail. Supersedes the old Admin → Ingestion page (its CSV / review /
 * data-health / Ops tools live under the Data tab).
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Activity, Cable, CalendarClock, Database, ListChecks, ScrollText, Workflow, Zap } from "lucide-react";
import { Page, PageHeader, Skeleton, StatCard } from "@/components/ui/page";
import { coworkApi, type CoworkOverview } from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";
import { ActivityTab, TasksTab } from "@/features/cowork/activity-tab";
import { AutomationsTab } from "@/features/cowork/automations-tab";
import { IngestionTools, Notices, useSay, type IngestionTab } from "@/features/cowork/ingestion-tools";
import { IntegrationsTab } from "@/features/cowork/integrations-tab";
import { JobsTab } from "@/features/cowork/jobs-tab";

const TABS = [
  ["overview", "Overview", Activity],
  ["integrations", "Integrations", Cable],
  ["schedules", "Schedules", CalendarClock],
  ["automations", "Automations", Zap],
  ["tasks", "Tasks", ListChecks],
  ["activity", "Activity", ScrollText],
  ["data", "Data tools", Database],
] as const;

type Tab = (typeof TABS)[number][0];

const INGESTION_TABS: IngestionTab[] = ["csv", "review", "health", "ops"];

export default function CoworkPage() {
  return (
    <Suspense fallback={<Page><Skeleton className="h-40" /></Page>}>
      <Cowork />
    </Suspense>
  );
}

function Cowork() {
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get("tab");
  const tab: Tab = TABS.some(([k]) => k === requested) ? (requested as Tab) : "overview";
  const sub = params.get("sub");
  const dataTab: IngestionTab = INGESTION_TABS.includes(sub as IngestionTab) ? (sub as IngestionTab) : "csv";
  const { say, message, error } = useSay();

  const setTab = (next: Tab, subTab?: IngestionTab) =>
    router.replace(next === "overview" ? "/cowork" : `/cowork?tab=${next}${subTab ? `&sub=${subTab}` : ""}`);

  return (
    <Page>
      <PageHeader
        kicker="Operations"
        title={
          <span className="inline-flex items-center gap-2">
            <Workflow className="h-6 w-6 text-gold" /> Co-work
          </span>
        }
        description="Integrations, schedules and task automations working alongside your team — with every run recorded."
      />

      <div role="tablist" aria-label="Co-work sections" className="mt-6 flex gap-1 overflow-x-auto rounded-xl border border-border bg-card p-1 text-sm font-medium shadow-card">
        {TABS.map(([key, label, Icon]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`inline-flex shrink-0 items-center gap-2 rounded-lg px-3.5 py-2 ${tab === key ? "bg-brand text-white shadow-card" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
          >
            <Icon className="h-4 w-4" /> {label}
          </button>
        ))}
      </div>

      <Notices message={message} error={error} />

      <div className="mt-6">
        {tab === "overview" && <OverviewTab onNavigate={setTab} />}
        {tab === "integrations" && <IntegrationsTab say={say} />}
        {tab === "schedules" && <JobsTab say={say} />}
        {tab === "automations" && <AutomationsTab say={say} />}
        {tab === "tasks" && <TasksTab say={say} />}
        {tab === "activity" && <ActivityTab say={say} />}
        {tab === "data" && <IngestionTools key={dataTab} initialTab={dataTab} />}
      </div>
    </Page>
  );
}

function OverviewTab({ onNavigate }: { onNavigate: (tab: Tab, sub?: IngestionTab) => void }) {
  const [ov, setOv] = useState<CoworkOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await coworkApi.overview();
    if (r.data) setOv(r.data);
    else setErr(r.error ?? "Failed to load");
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => clearInterval(t);
  }, [load]);

  if (err) return <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{err}</p>;
  if (!ov) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    );
  }

  const connected = ov.integrations.connected ?? 0;
  const problems = (ov.integrations.error ?? 0) + (ov.integrations.degraded ?? 0);
  const rate = ov.runs.success_rate;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <button type="button" className="text-start" onClick={() => onNavigate("integrations")}>
          <StatCard label="Integrations" value={connected} hint={problems ? `${problems} need attention` : `${ov.integrations.not_configured ?? 0} not configured`} tone={problems ? "warning" : "success"} />
        </button>
        <button type="button" className="text-start" onClick={() => onNavigate("schedules")}>
          <StatCard label="Scheduled jobs" value={`${ov.jobs.enabled}/${ov.jobs.total}`} hint={ov.jobs.failing ? `${ov.jobs.failing} failing` : "all healthy"} tone={ov.jobs.failing ? "danger" : "brand"} />
        </button>
        <button type="button" className="text-start" onClick={() => onNavigate("activity")}>
          <StatCard
            label={`Runs · last ${ov.runs.window_hours}h`}
            value={ov.runs.runs}
            hint={rate == null ? "no runs yet" : `${Math.round(rate)}% success · ${ov.runs.failed} failed`}
            tone={ov.runs.failed ? "warning" : "default"}
          />
        </button>
        <button type="button" className="text-start" onClick={() => onNavigate("automations")}>
          <StatCard label="Automations" value={`${ov.automations.enabled}/${ov.automations.total}`} hint={`${ov.automations.fired_total.toLocaleString("en-US")} firings total`} tone="brand" />
        </button>
        <button type="button" className="text-start" onClick={() => onNavigate("tasks")}>
          <StatCard label="Open tasks" value={ov.tasks_open} hint="created by automations" tone={ov.tasks_open ? "warning" : "default"} />
        </button>
        <button type="button" className="text-start" onClick={() => onNavigate("data", "review")}>
          <StatCard label="Review queue" value={ov.review_open} hint="records needing a human fix" tone={ov.review_open ? "warning" : "default"} />
        </button>
        <StatCard label="Avg job duration" value={ov.runs.avg_duration_ms != null ? `${ov.runs.avg_duration_ms} ms` : "—"} />
        <StatCard
          label="Last failure"
          value={ov.runs.last_failure ? relativeTime(ov.runs.last_failure.started_at) : "none"}
          hint={ov.runs.last_failure ? `${ov.runs.last_failure.job_id.replace(/_/g, " ")}: ${ov.runs.last_failure.error ?? ""}` : undefined}
          tone={ov.runs.last_failure ? "danger" : "success"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <QuickCard title="Where leads come from" body="Connect CRMs, webhooks and CSV drops. Each source is health-checked and shown with its last activity." cta="Open integrations" onClick={() => onNavigate("integrations")} />
        <QuickCard title="What runs on a schedule" body="Connector polling, retries, follow-ups, CRM write-back and retention. Toggle, change intervals, or run anything now." cta="Open schedules" onClick={() => onNavigate("schedules")} />
        <QuickCard title="Automate the next step" body="When a lead scores hot, hands off or confirms a viewing — create a task, notify the broker or start follow-ups." cta="Open automations" onClick={() => onNavigate("automations")} />
        <QuickCard title="Everything is recorded" body="Every run and firing with trigger, actor, duration and result. Failed runs can be retried in one click." cta="Open activity" onClick={() => onNavigate("activity")} />
      </div>
    </div>
  );
}

function QuickCard({ title, body, cta, onClick }: { title: string; body: string; cta: string; onClick: () => void }) {
  return (
    <div className="ui-card flex items-start justify-between gap-4 p-5">
      <div>
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{body}</p>
      </div>
      <button type="button" className="ui-btn-secondary ui-btn-sm shrink-0" onClick={onClick}>
        {cta}
      </button>
    </div>
  );
}
