"use client";

/**
 * CRM — one place to connect the CRM a broker already lives in and control the
 * two sync directions: pull (every N minutes, re-scored on arrival) and write-back
 * (scores, stages, assignments). Field mapping and raw connectors stay under Advanced.
 */

import { useCallback, useEffect, useState } from "react";
import { ArrowDownToLine, ArrowUpFromLine, ChevronDown, ChevronRight, Loader2, ShieldCheck, Zap } from "lucide-react";
import { Skeleton } from "@/components/ui/page";
import { coworkApi, type CoworkJob } from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";
import { useBrokerScope } from "@/lib/use-broker-scope";
import { ConnectionsTab } from "./connections-tab";
import { ConnectorsTab, type Say } from "./ingestion-tools";
import { RunStatus, Toggle, humanInterval } from "./shared";

const SYNC_JOBS = [
  { id: "poll_pull_connectors", title: "Pull from CRM", blurb: "New and changed leads come in on this interval and are scored on arrival.", icon: ArrowDownToLine },
  { id: "crm_writeback", title: "Write back to CRM", blurb: "Scores, stages and assignments go back to the CRM record they came from.", icon: ArrowUpFromLine },
] as const;

const INTERVALS = [300, 900, 1800, 3600, 3 * 3600, 6 * 3600, 24 * 3600];

export function CrmTab({ say }: { say: Say }) {
  const [jobs, setJobs] = useState<CoworkJob[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const { isAgent } = useBrokerScope();

  const load = useCallback(async () => {
    const r = await coworkApi.jobs();
    if (r.data) setJobs(r.data);
    else say(r, "");
  }, [say]);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = async (id: string, p: { enabled?: boolean; interval_s?: number }) => {
    setBusy(id);
    say(await coworkApi.patchJob(id, p), "Sync updated");
    setBusy(null);
    void load();
  };

  const runNow = async (id: string) => {
    setBusy(id);
    const r = await coworkApi.runJob(id);
    say(r, r.data ? `Sync ran: ${r.data.status}` : "");
    setBusy(null);
    void load();
  };

  return (
    <div className="space-y-10">
      <ConnectionsTab say={say} categories={["crm"]} title="Your CRM" intro="Connect the CRM you already use. It stays the source of truth; we pull leads, score them, and write results back. Keys are stored encrypted and never shown again." />

      <section aria-labelledby="sync-title">
        <div className="mb-3 flex items-start gap-3">
          <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-muted text-foreground/70">
            <ShieldCheck className="h-4 w-4" />
          </span>
          <div>
            <h2 id="sync-title" className="text-base font-semibold text-foreground">
              Sync schedule
            </h2>
            <p className="text-sm text-muted-foreground">Both directions are idempotent — running twice never duplicates a record.</p>
          </div>
        </div>
        {!jobs ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Skeleton className="h-32" />
            <Skeleton className="h-32" />
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {SYNC_JOBS.map((spec) => {
              const job = jobs.find((j) => j.id === spec.id);
              if (!job) return null;
              const Icon = spec.icon;
              return (
                <article key={job.id} className="ui-card flex flex-col gap-3 p-4">
                  <header className="flex items-start justify-between gap-2">
                    <div className="flex items-start gap-2">
                      <Icon className="mt-0.5 h-4 w-4 text-brand" />
                      <div>
                        <p className="text-sm font-semibold text-foreground">{spec.title}</p>
                        <p className="text-xs text-muted-foreground">{spec.blurb}</p>
                      </div>
                    </div>
                    <Toggle checked={job.enabled} onChange={(v) => void patch(job.id, { enabled: v })} label={`${spec.title} enabled`} disabled={busy === job.id} />
                  </header>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <label className="flex items-center gap-2 text-muted-foreground">
                      Every
                      <select className="ui-input" value={job.interval_s} onChange={(e) => void patch(job.id, { interval_s: Number(e.target.value) })} disabled={busy === job.id}>
                        {Array.from(new Set([...INTERVALS, job.interval_s]))
                          .sort((a, b) => a - b)
                          .map((s) => (
                            <option key={s} value={s}>
                              {humanInterval(s)}
                            </option>
                          ))}
                      </select>
                    </label>
                    <span className="ms-auto flex items-center gap-2 text-muted-foreground">
                      {job.last_run ? (
                        <>
                          <RunStatus status={job.last_run.status} /> {relativeTime(job.last_run.started_at)}
                        </>
                      ) : (
                        "never run"
                      )}
                    </span>
                  </div>
                  <button type="button" className="ui-btn-secondary ui-btn-sm self-start" onClick={() => void runNow(job.id)} disabled={busy === job.id}>
                    {busy === job.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />} Sync now
                  </button>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {!isAgent && (
      <section>
        <button type="button" className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground" onClick={() => setAdvanced((a) => !a)} aria-expanded={advanced}>
          {advanced ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Advanced: field mapping, CSV import and legacy connectors
        </button>
        {advanced && (
          <div className="mt-4">
            <ConnectorsTab say={say} />
          </div>
        )}
      </section>
      )}
    </div>
  );
}
