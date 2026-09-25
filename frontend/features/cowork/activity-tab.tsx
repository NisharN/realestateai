"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Check, ListChecks, RefreshCw, ScrollText, X } from "lucide-react";
import { Badge, EmptyState, Section, Skeleton } from "@/components/ui/page";
import { coworkApi, type AuditEntry, type CoworkTask } from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";
import type { Say } from "./ingestion-tools";
import { RunStatus, summaryText } from "./shared";

export function TasksTab({ say }: { say: Say }) {
  const [tasks, setTasks] = useState<CoworkTask[] | null>(null);
  const [status, setStatus] = useState<CoworkTask["status"] | "all">("open");

  const load = useCallback(async () => {
    const r = await coworkApi.tasks(status === "all" ? undefined : status);
    if (r.data) setTasks(r.data);
    else say(r, "");
  }, [say, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const set = async (id: string, next: CoworkTask["status"]) => {
    if (say(await coworkApi.patchTask(id, next), next === "done" ? "Task completed" : "Task dismissed")) void load();
  };

  return (
    <Section
      title={
        <>
          <ListChecks className="h-4 w-4 text-brand" /> Tasks created by automations
        </>
      }
      count={tasks?.length}
      actions={
        <div role="tablist" aria-label="Task status" className="flex gap-1 rounded-lg bg-muted p-0.5 text-xs">
          {(["open", "done", "dismissed", "all"] as const).map((s) => (
            <button key={s} role="tab" aria-selected={status === s} onClick={() => setStatus(s)} className={`rounded-md px-2.5 py-1 capitalize ${status === s ? "bg-card font-medium text-foreground shadow-card" : "text-muted-foreground"}`}>
              {s}
            </button>
          ))}
        </div>
      }
    >
      {!tasks ? (
        <Skeleton className="h-24" />
      ) : tasks.length === 0 ? (
        <EmptyState title={status === "open" ? "No open tasks" : "No tasks"} body="Tasks appear here when a “Create task” automation fires." />
      ) : (
        <ul className="divide-y divide-border">
          {tasks.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{t.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {t.lead_id && (
                    <Link href={`/broker/leads/${t.lead_id}`} className="text-brand hover:underline">
                      Lead {t.lead_id.slice(0, 8)}
                    </Link>
                  )}
                  {t.broker_id ? ` · broker ${t.broker_id.slice(0, 8)}` : " · unassigned"} · due in {t.due_in_hours}h · created {relativeTime(t.created_at)}
                </p>
              </div>
              <Badge tone={t.status === "open" ? "warning" : t.status === "done" ? "success" : "neutral"}>{t.status}</Badge>
              {t.status === "open" && (
                <div className="flex gap-1">
                  <button type="button" className="ui-btn-secondary ui-btn-sm" onClick={() => void set(t.id, "done")}>
                    <Check className="h-3.5 w-3.5" /> Done
                  </button>
                  <button type="button" className="ui-btn-ghost ui-btn-sm" aria-label="Dismiss task" onClick={() => void set(t.id, "dismissed")}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function ActivityTab({ say }: { say: Say }) {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [kind, setKind] = useState<"all" | "job" | "automation">("all");

  const load = useCallback(async () => {
    const r = await coworkApi.audit(200);
    if (r.data) setEntries(r.data);
    else say(r, "");
  }, [say]);

  useEffect(() => {
    void load();
  }, [load]);

  const shown = (entries ?? []).filter((e) => kind === "all" || e.kind === kind);

  return (
    <Section
      title={
        <>
          <ScrollText className="h-4 w-4 text-brand" /> Audit trail
        </>
      }
      count={shown.length}
      actions={
        <div className="flex items-center gap-2">
          <div role="tablist" aria-label="Audit kind" className="flex gap-1 rounded-lg bg-muted p-0.5 text-xs">
            {(["all", "job", "automation"] as const).map((k) => (
              <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)} className={`rounded-md px-2.5 py-1 capitalize ${kind === k ? "bg-card font-medium text-foreground shadow-card" : "text-muted-foreground"}`}>
                {k === "all" ? "All" : k === "job" ? "Jobs" : "Automations"}
              </button>
            ))}
          </div>
          <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={() => void load()} aria-label="Refresh audit">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      }
    >
      {!entries ? (
        <Skeleton className="h-40" />
      ) : shown.length === 0 ? (
        <EmptyState title="No activity yet" body="Every job run and automation firing is recorded here with who or what triggered it." />
      ) : (
        <ol className="relative ms-2 border-s border-border">
          {shown.map((e) => (
            <li key={`${e.kind}-${e.id}`} className="relative ps-6 pb-5 last:pb-0">
              <span
                className={`absolute -start-[5px] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-card ${
                  e.status === "failed" ? "bg-danger" : e.status === "running" ? "bg-brand" : "bg-success"
                }`}
                aria-hidden
              />
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone={e.kind === "job" ? "brand" : "gold"}>{e.kind}</Badge>
                <span className="font-medium text-foreground">{e.subject}</span>
                <RunStatus status={e.status} />
                <span className="text-xs text-muted-foreground">
                  {e.trigger ?? ""}
                  {e.actor ? ` · by ${e.actor}` : ""} · {e.at ? relativeTime(e.at) : ""}
                </span>
              </div>
              {summaryText(e.detail) && <p className={`mt-1 text-xs ${e.status === "failed" ? "text-danger" : "text-muted-foreground"}`}>{summaryText(e.detail)}</p>}
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}
