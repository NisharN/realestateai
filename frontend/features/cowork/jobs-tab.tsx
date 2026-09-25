"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Clock, Play, RefreshCw } from "lucide-react";
import { Badge, EmptyState, Section, Skeleton } from "@/components/ui/page";
import { coworkApi, type CoworkJob, type JobRun } from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";
import type { Say } from "./ingestion-tools";
import { RunStatus, Toggle, humanInterval, summaryText } from "./shared";

const CATEGORY_LABEL: Record<CoworkJob["category"], string> = {
  intake: "Lead intake",
  engagement: "Engagement",
  sync: "CRM sync",
  compliance: "Compliance",
  housekeeping: "Housekeeping",
};

const INTERVALS = [30, 60, 120, 300, 900, 1800, 3600, 21_600, 86_400];

export function JobsTab({ say }: { say: Say }) {
  const [jobs, setJobs] = useState<CoworkJob[] | null>(null);
  const [runs, setRuns] = useState<JobRun[]>([]);
  const [filter, setFilter] = useState<{ job_id?: string; status?: JobRun["status"] }>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [j, r] = await Promise.all([coworkApi.jobs(), coworkApi.runs({ ...filter, limit: 60 })]);
    if (j.data) setJobs(j.data);
    else say(j, "");
    if (r.data) setRuns(r.data);
  }, [say, filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const runNow = async (id: string) => {
    setBusy(id);
    const r = await coworkApi.runJob(id);
    setBusy(null);
    if (say(r, r.data?.status === "failed" ? `Job failed: ${r.data.error ?? "unknown error"}` : `Ran ${id.replace(/_/g, " ")} · ${summaryText(r.data?.summary) || "done"}`)) {
      void load();
    }
  };

  const patch = async (id: string, patch: { enabled?: boolean; interval_s?: number }) => {
    const r = await coworkApi.patchJob(id, patch);
    if (say(r, "Schedule updated")) void load();
  };

  if (!jobs) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    );
  }

  const categories = Array.from(new Set(jobs.map((j) => j.category)));

  return (
    <div className="space-y-8">
      {categories.map((cat) => (
        <section key={cat}>
          <h2 className="mb-3 text-sm font-semibold text-foreground">{CATEGORY_LABEL[cat]}</h2>
          <div className="space-y-3">
            {jobs
              .filter((j) => j.category === cat)
              .map((job) => (
                <article key={job.id} className={`ui-card p-4 ${job.enabled ? "" : "opacity-70"}`}>
                  <div className="flex flex-wrap items-start gap-4">
                    <Toggle checked={job.enabled} label={`Enable ${job.label}`} onChange={(v) => void patch(job.id, { enabled: v })} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-semibold text-foreground">{job.label}</p>
                        {job.last_run?.status === "failed" && (
                          <Badge tone="danger">
                            <AlertTriangle className="me-1 h-3 w-3" /> last run failed
                          </Badge>
                        )}
                      </div>
                      <p className="mt-0.5 text-xs text-muted-foreground">{job.description}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" /> every
                          <select
                            aria-label={`Interval for ${job.label}`}
                            className="ui-input h-6 w-auto px-1.5 py-0 text-[11px]"
                            value={job.interval_s}
                            onChange={(e) => void patch(job.id, { interval_s: Number(e.target.value) })}
                          >
                            {(INTERVALS.includes(job.interval_s) ? INTERVALS : [...INTERVALS, job.interval_s].sort((a, b) => a - b)).map((s) => (
                              <option key={s} value={s}>
                                {humanInterval(s)}
                              </option>
                            ))}
                          </select>
                        </span>
                        <span>Last run {job.last_run ? relativeTime(job.last_run.started_at) : "never"}</span>
                        <span>Next {job.enabled ? (job.next_run_at ? relativeTime(job.next_run_at) : "on next tick") : "paused"}</span>
                        {job.last_run?.summary && Object.keys(job.last_run.summary).length > 0 && (
                          <span className="truncate">{summaryText(job.last_run.summary)}</span>
                        )}
                      </div>
                      {job.last_run?.error && <p className="mt-2 rounded-lg bg-danger-soft px-2 py-1 text-xs text-danger">{job.last_run.error}</p>}
                    </div>
                    <button
                      type="button"
                      className="ui-btn-secondary ui-btn-sm"
                      disabled={busy === job.id}
                      onClick={() => void runNow(job.id)}
                    >
                      {busy === job.id ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                      Run now
                    </button>
                  </div>
                </article>
              ))}
          </div>
        </section>
      ))}

      <Section
        title="Run history"
        count={runs.length}
        actions={
          <div className="flex items-center gap-2">
            <select aria-label="Filter by job" className="ui-input h-8 w-auto text-xs" value={filter.job_id ?? ""} onChange={(e) => setFilter((f) => ({ ...f, job_id: e.target.value || undefined }))}>
              <option value="">All jobs</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.label}
                </option>
              ))}
            </select>
            <select aria-label="Filter by status" className="ui-input h-8 w-auto text-xs" value={filter.status ?? ""} onChange={(e) => setFilter((f) => ({ ...f, status: (e.target.value || undefined) as JobRun["status"] | undefined }))}>
              <option value="">Any status</option>
              <option value="success">Success</option>
              <option value="failed">Failed</option>
              <option value="running">Running</option>
            </select>
            <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        }
      >
        {runs.length === 0 ? (
          <EmptyState title="No runs yet" body="Run a job manually or wait for the scheduler." />
        ) : (
          <div className="-m-5 overflow-x-auto">
            <table className="ui-table w-full text-sm">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Job</th>
                  <th>Trigger</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Result</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td className="whitespace-nowrap text-muted-foreground">{relativeTime(r.started_at)}</td>
                    <td className="font-medium">{jobs.find((j) => j.id === r.job_id)?.label ?? r.job_id}</td>
                    <td className="text-muted-foreground">{r.trigger}{r.actor ? ` · ${r.actor}` : ""}</td>
                    <td>
                      <RunStatus status={r.status} />
                    </td>
                    <td className="tabular text-muted-foreground">{r.duration_ms != null ? `${r.duration_ms} ms` : "—"}</td>
                    <td className="max-w-xs truncate text-xs text-muted-foreground" title={r.error ?? summaryText(r.summary)}>
                      {r.error ? <span className="text-danger">{r.error}</span> : summaryText(r.summary) || "—"}
                    </td>
                    <td className="text-end">
                      {r.status === "failed" && (
                        <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={() => void runNow(r.job_id)}>
                          Retry
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
