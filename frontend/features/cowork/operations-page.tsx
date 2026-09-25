"use client";

/**
 * Operations — the setup side of a broker's business, in four plain tabs:
 * Connections (lead sources, WhatsApp, voice notes, calendar, AI), CRM (connect
 * + sync schedule), Routines (scheduled work), Insights (ask questions of the
 * pipeline). Everything else — task rules, raw job scheduler, activity audit,
 * CSV/review/data-health tools — sits under Advanced so it never crowds the day job.
 */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Cable, ChevronDown, Database, Link2, ListChecks, ScrollText, Sparkles, Workflow, Zap, type LucideIcon } from "lucide-react";
import { Page, PageHeader, Skeleton } from "@/components/ui/page";
import { Copilot } from "@/components/copilot";
import { ActivityTab, TasksTab } from "@/features/cowork/activity-tab";
import { AutomationsTab } from "@/features/cowork/automations-tab";
import { ConnectionsTab } from "@/features/cowork/connections-tab";
import { CrmTab } from "@/features/cowork/crm-tab";
import { IngestionTools, Notices, useSay, type IngestionTab } from "@/features/cowork/ingestion-tools";
import { JobsTab } from "@/features/cowork/jobs-tab";
import { RoutinesTab } from "@/features/cowork/routines-tab";
import { useBrokerScope } from "@/lib/use-broker-scope";

const TABS = [
  ["connections", "Connections", Cable],
  ["crm", "CRM", Link2],
  ["routines", "Routines", Workflow],
  ["insights", "Insights", Sparkles],
] as const;

const ADVANCED = [
  ["automations", "Task rules", Zap],
  ["schedules", "Background jobs", ListChecks],
  ["activity", "Activity log", ScrollText],
  ["data", "Data tools", Database],
] as const;

export type Section = (typeof TABS)[number][0];
type Tab = Section | (typeof ADVANCED)[number][0];
const SECTIONS: readonly Section[] = TABS.map(([k]) => k);

const ALL: readonly (readonly [Tab, string, LucideIcon])[] = [...TABS, ...ADVANCED];
const INGESTION_TABS: IngestionTab[] = ["csv", "review", "health", "ops"];

const DESCRIPTION: Record<Tab, string> = {
  connections: "Plug in where your leads come from and how you talk to them. Test every connection and webhook before it goes live.",
  crm: "Your CRM stays the source of truth. Pull on a schedule, score on arrival, write results back.",
  routines: "Work that runs for you on a schedule — inbox to CRM, re-engaging quiet leads, voice-note follow-ups, listing hygiene.",
  insights: "Ask about your pipeline in plain language and act on the answer.",
  automations: "Event rules: when a lead scores hot, is handed off or confirms a viewing, do something.",
  schedules: "Background jobs that keep the platform ticking. Change intervals or run anything now.",
  activity: "Every run and rule firing, with trigger, actor, duration and result.",
  data: "CSV import, review queue, data health and platform health.",
};

export function OperationsPage({ section }: { section?: Section }) {
  return (
    <Suspense
      fallback={
        <Page>
          <Skeleton className="h-40" />
        </Page>
      }
    >
      <Cowork section={section} />
    </Suspense>
  );
}

function Cowork({ section }: { section?: Section }) {
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get("tab");
  const tab: Tab = section ?? (ALL.some(([k]) => k === requested) ? (requested as Tab) : "connections");
  const sub = params.get("sub");
  const dataTab: IngestionTab = INGESTION_TABS.includes(sub as IngestionTab) ? (sub as IngestionTab) : "csv";
  const { say, message, error } = useSay();
  const [moreOpen, setMoreOpen] = useState(false);
  const { isAgent } = useBrokerScope();

  useEffect(() => {
    if (!section && !ADVANCED.some(([k]) => k === requested)) router.replace(`/cowork/${tab}${params.toString() ? `?${params.toString()}` : ""}`);
  }, [section, requested, tab, router, params]);

  const inAdvanced = ADVANCED.some(([k]) => k === tab);

  const setTab = (next: Tab, subTab?: IngestionTab) => {
    setMoreOpen(false);
    router.replace(SECTIONS.includes(next as Section) ? `/cowork/${next}` : `/cowork?tab=${next}${subTab ? `&sub=${subTab}` : ""}`);
  };

  return (
    <Page>
      <PageHeader kicker="Operations" title={ALL.find(([k]) => k === tab)?.[1] ?? "Operations"} description={DESCRIPTION[tab]} />

      <div className="mt-5 flex items-center gap-1 border-b border-border text-sm">
        <div role="tablist" aria-label="Operations sections" className="flex gap-1 overflow-x-auto">
          {TABS.map(([key, label, Icon]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={`-mb-px inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 transition-colors ${tab === key ? "border-ink font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
            >
              <Icon className="h-3.5 w-3.5" /> {label}
            </button>
          ))}
        </div>
        {!isAgent && (
        <div className="relative ms-auto">
          <button
            type="button"
            onClick={() => setMoreOpen((o) => !o)}
            aria-haspopup="menu"
            aria-expanded={moreOpen}
            className={`-mb-px inline-flex items-center gap-1 border-b-2 px-3 py-2 transition-colors ${inAdvanced ? "border-ink font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            {inAdvanced ? ALL.find(([k]) => k === tab)?.[1] : "Advanced"} <ChevronDown className="h-3.5 w-3.5" />
          </button>
          {moreOpen && (
            <ul role="menu" className="absolute end-0 top-full z-20 mt-1 w-56 rounded-xl border border-border bg-card p-1 shadow-lg">
              {ADVANCED.map(([key, label, Icon]) => (
                <li key={key} role="none">
                  <button
                    role="menuitem"
                    type="button"
                    onClick={() => setTab(key)}
                    className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm hover:bg-muted ${tab === key ? "font-medium text-foreground" : "text-muted-foreground"}`}
                  >
                    <Icon className="h-3.5 w-3.5" /> {label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        )}
      </div>

      <Notices message={message} error={error} />

      <div className="mt-6">
        {tab === "connections" && <ConnectionsTab say={say} />}
        {tab === "crm" && <CrmTab say={say} />}
        {tab === "routines" && <RoutinesTab say={say} />}
        {tab === "insights" && <Copilot />}
        {tab === "automations" && <AutomationsTab say={say} />}
        {tab === "schedules" && <JobsTab say={say} />}
        {tab === "activity" && (
          <div className="space-y-8">
            <ActivityTab say={say} />
            <TasksTab say={say} />
          </div>
        )}
        {tab === "data" && <IngestionTools key={dataTab} initialTab={dataTab} />}
      </div>
    </Page>
  );
}
