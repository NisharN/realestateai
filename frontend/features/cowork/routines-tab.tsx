"use client";

/**
 * Routines — the things a broker wants done for them on a schedule.
 * Template-first: pick "Inbox → CRM", "Re-engage quiet leads", "Voice-note follow-up"…
 * or start blank. The builder is one vertical column: When → Which leads → Then do.
 * Each step is a plain-language card with an inline connection picker; run
 * results appear under the routine so the broker sees what actually happened.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import {
  ArrowDown,
  Bot,
  Cable,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  Loader2,
  Pause,
  Play,
  Plus,
  Sparkles,
  Trash2,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { Badge, Skeleton, type BadgeTone } from "@/components/ui/page";
import {
  coworkApi,
  type Connection,
  type Routine,
  type RoutineCatalog,
  type RoutineInput,
  type RoutineRun,
  type RoutineSchedule,
  type RoutineStep,
  type RoutineStepSpec,
  type RoutineTemplate,
} from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";
import type { Say } from "./ingestion-tools";

const RUN_TONE: Record<NonNullable<Routine["last_status"]>, BadgeTone> = { success: "success", partial: "warning", failed: "danger" };

const CATEGORY_LABEL: Record<string, string> = {
  intake: "Leads in",
  follow_up: "Follow-up",
  engagement: "Follow-up",
  viewings: "Viewings",
  analytics: "Insights",
  reporting: "Insights",
  inventory: "Listings",
  hygiene: "Housekeeping",
  compliance: "Housekeeping",
  sync: "CRM sync",
};

const GROUP_ICON: Record<RoutineStepSpec["group"], LucideIcon> = { connector: Cable, data: Database, llm: Bot };

/** Which step types are "pick leads", which are "do something". */
const SOURCE_TYPES = new Set(["connector.pull_leads", "connector.pull_listings", "leads.select", "viewings.select", "analytics.query"]);
const ADVANCED_TYPES = new Set(["job.run", "listings.validate", "connector.notify", "connector.send_email", "llm.summarize"]);

const PARAM_LABEL: Record<string, string> = {
  stage: "Stage",
  band: "Score band",
  source: "Source",
  min_score: "Minimum score",
  stale_hours: "Quiet for at least (hours)",
  created_within_hours: "Created in the last (hours)",
  limit: "Max leads",
  within_hours: "Within (hours)",
  template: "Message",
  use_drafts: "Use AI drafts",
  to: "To",
  subject: "Subject",
  text: "Text",
  focus: "Focus on",
  channel: "Channel",
  tone: "Tone",
  language: "Language",
  title: "Task title",
  due_in_hours: "Due in (hours)",
  job_id: "Job",
  question: "Question",
  metric: "Metric",
  area: "Area",
  max_score: "Only if score ≤",
  reason: "Reason",
  stale_days: "Stale after (days)",
  path: "API path",
};

export function RoutinesTab({ say }: { say: Say }) {
  const params = useSearchParams();
  const [catalog, setCatalog] = useState<RoutineCatalog | null>(null);
  const [routines, setRoutines] = useState<Routine[] | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [editing, setEditing] = useState<{ routine?: Routine; template?: RoutineTemplate } | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);

  const load = useCallback(async () => {
    const [cat, list, conns] = await Promise.all([coworkApi.routineCatalog(), coworkApi.routines(), coworkApi.connections()]);
    if (cat.data) setCatalog(cat.data);
    else say(cat, "");
    if (list.data) setRoutines(list.data);
    else say(list, "");
    if (conns.data) setConnections(conns.data.connections);
  }, [say]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!catalog) return;
    const tpl = params.get("template");
    if (tpl) {
      const t = catalog.templates.find((x) => x.id === tpl);
      if (t) setEditing({ template: t });
    } else if (params.get("new")) {
      setEditing({});
    }
  }, [catalog, params]);

  if (!catalog || !routines) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    );
  }

  const usedTemplates = new Set(routines.map((r) => r.template_id).filter(Boolean));

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {routines.length === 0 ? "Pick a starting point below — every routine runs on your schedule and shows you what it did." : `${routines.filter((r) => r.enabled).length} of ${routines.length} routines active.`}
        </p>
        <div className="flex items-center gap-2">
          <button type="button" className="ui-btn-secondary ui-btn-sm" onClick={() => setShowTemplates((s) => !s)}>
            <Sparkles className="h-3.5 w-3.5" /> Templates
          </button>
          <button type="button" className="ui-btn-primary ui-btn-sm" onClick={() => setEditing({})}>
            <Plus className="h-3.5 w-3.5" /> New routine
          </button>
        </div>
      </div>

      {(showTemplates || routines.length === 0) && (
        <section aria-label="Templates" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {catalog.templates.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setEditing({ template: t })}
              className="ui-card flex flex-col items-start gap-2 p-4 text-start transition hover:border-brand/50 hover:bg-brand/[0.03]"
            >
              <span className="flex w-full items-center justify-between gap-2">
                <Badge tone="brand">{CATEGORY_LABEL[t.category] ?? t.category}</Badge>
                {usedTemplates.has(t.id) && <span className="text-[11px] text-muted-foreground">in use</span>}
              </span>
              <span className="text-sm font-semibold text-foreground">{t.name}</span>
              <span className="line-clamp-2 text-xs text-muted-foreground">{t.description}</span>
              <span className="mt-auto flex items-center gap-1 text-[11px] text-muted-foreground">
                <Clock className="h-3 w-3" /> {scheduleLabel(t.schedule)} · {t.steps.length} steps
              </span>
            </button>
          ))}
        </section>
      )}

      {routines.length > 0 && (
        <section aria-label="My routines" className="space-y-3">
          {routines.map((r) => (
            <RoutineRow key={r.id} routine={r} say={say} onChanged={load} onEdit={() => setEditing({ routine: r })} />
          ))}
        </section>
      )}

      {editing && (
        <Builder
          catalog={catalog}
          connections={connections}
          routine={editing.routine}
          template={editing.template}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
          say={say}
        />
      )}
    </div>
  );
}

function scheduleLabel(s: RoutineSchedule): string {
  if (s.kind === "interval" && s.seconds) {
    const h = s.seconds / 3600;
    return h >= 1 ? `every ${h % 1 === 0 ? h : h.toFixed(1)}h` : `every ${Math.round(s.seconds / 60)} min`;
  }
  if (s.kind === "weekly") return `weekly ${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][s.weekday ?? 0]} ${s.at ?? ""}`.trim();
  return `daily ${s.at ?? "09:00"}`;
}

function RoutineRow({ routine: r, say, onChanged, onEdit }: { routine: Routine; say: Say; onChanged: () => void; onEdit: () => void }) {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [runs, setRuns] = useState<RoutineRun[] | null>(null);

  const loadRuns = async () => {
    const res = await coworkApi.routineRuns(r.id, 5);
    if (res.data) setRuns(res.data);
  };

  const run = async () => {
    setBusy(true);
    const res = await coworkApi.runRoutine(r.id);
    say(res, res.data ? `Ran “${r.name}”: ${summarize(res.data)}` : "");
    setBusy(false);
    setOpen(true);
    await loadRuns();
    onChanged();
  };

  const toggle = async () => {
    setBusy(true);
    say(await coworkApi.patchRoutine(r.id, { enabled: !r.enabled }), r.enabled ? "Paused" : "Activated");
    setBusy(false);
    onChanged();
  };

  const remove = async () => {
    if (!window.confirm(`Delete “${r.name}”?`)) return;
    setBusy(true);
    say(await coworkApi.deleteRoutine(r.id), "Routine deleted");
    setBusy(false);
    onChanged();
  };

  return (
    <article className="ui-card">
      <div className="flex items-center gap-3 p-4">
        <button
          type="button"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-muted text-foreground/70"
          onClick={() => {
            setOpen((o) => !o);
            if (!runs) void loadRuns();
          }}
          aria-expanded={open}
          aria-label="Show recent runs"
        >
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={onEdit} className="truncate text-sm font-semibold text-foreground hover:underline">
              {r.name}
            </button>
            {!r.enabled && <Badge tone="neutral">paused</Badge>}
            {r.last_status && <Badge tone={RUN_TONE[r.last_status]}>{r.last_status}</Badge>}
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {r.schedule_label} · {r.steps.length} steps
            {r.last_run_at ? ` · last run ${relativeTime(r.last_run_at)}` : " · never run"}
            {r.enabled && r.next_run_at ? ` · next ${relativeTime(r.next_run_at)}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button type="button" className="ui-btn-secondary ui-btn-sm" onClick={run} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />} Run now
          </button>
          <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={toggle} disabled={busy} aria-label={r.enabled ? "Pause" : "Activate"}>
            {r.enabled ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          </button>
          <button type="button" className="ui-btn-ghost ui-btn-sm text-danger" onClick={remove} disabled={busy} aria-label="Delete">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      {open && (
        <div className="border-t border-border px-4 py-3">
          {!runs ? (
            <Skeleton className="h-10" />
          ) : runs.length === 0 ? (
            <p className="text-xs text-muted-foreground">No runs yet.</p>
          ) : (
            <ul className="space-y-2">
              {runs.map((run) => (
                <li key={run.id} className="text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={run.status === "success" ? "success" : run.status === "failed" ? "danger" : run.status === "running" ? "brand" : "warning"}>{run.status}</Badge>
                    <span className="text-muted-foreground">{relativeTime(run.started_at)}</span>
                    <span className="text-foreground/80">{summarize(run)}</span>
                  </div>
                  {run.steps.some((s) => s.status === "failed") && (
                    <ul className="mt-1 ms-2 space-y-0.5 text-danger">
                      {run.steps
                        .filter((s) => s.status === "failed")
                        .map((s, i) => (
                          <li key={i}>
                            {s.type}: {s.error}
                          </li>
                        ))}
                    </ul>
                  )}
                  {run.summary.digest && <p className="mt-1 ms-2 whitespace-pre-line text-foreground/80">{run.summary.digest}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </article>
  );
}

function summarize(run: RoutineRun): string {
  const parts: string[] = [];
  if (run.summary.leads != null) parts.push(`${run.summary.leads} leads`);
  if (run.summary.viewings != null) parts.push(`${run.summary.viewings} viewings`);
  if (run.summary.listing_issues) parts.push(`${run.summary.listing_issues} listing issues`);
  const ok = run.steps.filter((s) => s.status === "success" || s.status === "simulated").length;
  parts.push(`${ok}/${run.steps.length} steps ok`);
  if (run.error) parts.push(run.error);
  return parts.join(" · ");
}

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

interface Draft {
  name: string;
  description: string;
  schedule: RoutineSchedule;
  steps: RoutineStep[];
  enabled: boolean;
  template_id: string | null;
}

function draftFrom(routine?: Routine, template?: RoutineTemplate, connections: Connection[] = []): Draft {
  if (routine) {
    return { name: routine.name, description: routine.description ?? "", schedule: routine.schedule, steps: routine.steps.map((s) => ({ ...s })), enabled: routine.enabled, template_id: routine.template_id };
  }
  if (template) {
    return {
      name: template.name,
      description: template.description,
      schedule: template.schedule,
      steps: template.steps.map((s) => ({
        type: s.type,
        params: { ...(s.params ?? {}) },
        connection_id: s.provider ? connections.find((c) => c.provider === s.provider && c.status === "active")?.id ?? null : null,
      })),
      enabled: true,
      template_id: template.id,
    };
  }
  return { name: "", description: "", schedule: { kind: "daily", at: "09:00", tz: "Asia/Dubai" }, steps: [{ type: "leads.select", params: { limit: 50 } }], enabled: true, template_id: null };
}

function Builder({
  catalog,
  connections,
  routine,
  template,
  onClose,
  onSaved,
  say,
}: {
  catalog: RoutineCatalog;
  connections: Connection[];
  routine?: Routine;
  template?: RoutineTemplate;
  onClose: () => void;
  onSaved: () => void;
  say: Say;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(routine, template, connections));
  const [saving, setSaving] = useState(false);
  const [picker, setPicker] = useState<"source" | "action" | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [preview, setPreview] = useState<RoutineRun | null>(null);
  const specs = useMemo(() => new Map(catalog.steps.map((s) => [s.type, s])), [catalog.steps]);

  const update = (i: number, patch: Partial<RoutineStep>) => setDraft((d) => ({ ...d, steps: d.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) }));
  const removeStep = (i: number) => setDraft((d) => ({ ...d, steps: d.steps.filter((_, j) => j !== i) }));
  const addStep = (type: string) => {
    setDraft((d) => ({ ...d, steps: [...d.steps, { type, params: {}, connection_id: null }] }));
    setPicker(null);
  };

  const toInput = (): RoutineInput => ({
    name: draft.name.trim() || "Untitled routine",
    description: draft.description.trim() || null,
    schedule: draft.schedule,
    steps: draft.steps,
    enabled: draft.enabled,
    template_id: draft.template_id,
  });

  const save = async (runAfter = false) => {
    setSaving(true);
    const input = toInput();
    const r = routine ? await coworkApi.patchRoutine(routine.id, input) : await coworkApi.createRoutine(input);
    if (r.data && runAfter) {
      const run = await coworkApi.runRoutine(r.data.id);
      if (run.data) setPreview(run.data);
      say(run, run.data ? `Ran: ${summarize(run.data)}` : "");
    } else {
      say(r, routine ? "Routine saved" : "Routine created");
    }
    setSaving(false);
    if (r.data && !runAfter) onSaved();
  };

  const missingConnection = draft.steps.some((s) => specs.get(s.type)?.needs_connection && !s.connection_id);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" role="dialog" aria-modal="true" aria-labelledby="builder-title" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="flex h-full w-full max-w-xl flex-col bg-card shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-border p-5">
          <div className="min-w-0 flex-1">
            <p className="ui-kicker">{routine ? "Edit routine" : template ? "From template" : "New routine"}</p>
            <input
              id="builder-title"
              className="mt-1 w-full border-0 bg-transparent p-0 text-lg font-semibold text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-0"
              value={draft.name}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              placeholder="Name this routine"
              aria-label="Routine name"
              maxLength={120}
            />
          </div>
          <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          <StepShell label="When" icon={Clock}>
            <ScheduleEditor value={draft.schedule} onChange={(schedule) => setDraft((d) => ({ ...d, schedule }))} />
          </StepShell>

          {draft.steps.map((step, i) => {
            const spec = specs.get(step.type);
            if (!spec) return null;
            const isSource = SOURCE_TYPES.has(step.type);
            const label = isSource ? (i === 0 ? "Start with" : "Also") : "Then";
            return (
              <div key={step.id ?? i}>
                <div className="flex justify-center py-1 text-muted-foreground">
                  <ArrowDown className="h-4 w-4" />
                </div>
                <StepShell label={label} icon={GROUP_ICON[spec.group]} onRemove={draft.steps.length > 1 ? () => removeStep(i) : undefined}>
                  <p className="text-sm font-medium text-foreground">{spec.label}</p>
                  {spec.needs_connection && (
                    <ConnectionPicker spec={spec} connections={connections} value={step.connection_id ?? null} onChange={(connection_id) => update(i, { connection_id })} />
                  )}
                  <ParamsEditor spec={spec} params={step.params} stages={catalog.stages} jobs={catalog.jobs} onChange={(params) => update(i, { params })} />
                </StepShell>
              </div>
            );
          })}

          <div className="flex justify-center py-1 text-muted-foreground">
            <ArrowDown className="h-4 w-4" />
          </div>
          {picker ? (
            <StepPicker
              catalog={catalog.steps}
              kind={picker}
              showAdvanced={showAdvanced}
              onToggleAdvanced={() => setShowAdvanced((s) => !s)}
              onPick={addStep}
              onCancel={() => setPicker(null)}
            />
          ) : (
            <div className="flex flex-wrap gap-2">
              <button type="button" className="ui-btn-secondary ui-btn-sm" onClick={() => setPicker("source")}>
                <Plus className="h-3.5 w-3.5" /> Add leads / data
              </button>
              <button type="button" className="ui-btn-primary ui-btn-sm" onClick={() => setPicker("action")}>
                <Plus className="h-3.5 w-3.5" /> Add an action
              </button>
            </div>
          )}

          {preview && (
            <div className="rounded-xl border border-border bg-muted/40 p-3 text-xs">
              <p className="mb-1 font-medium text-foreground">Run result · {summarize(preview)}</p>
              <ul className="space-y-0.5">
                {preview.steps.map((s, i) => (
                  <li key={i} className={s.status === "failed" ? "text-danger" : "text-foreground/80"}>
                    {specs.get(s.type)?.label ?? s.type} — {s.status}
                    {s.error ? `: ${s.error}` : ""}
                    {Object.entries(s.summary)
                      .filter(([, v]) => typeof v === "number" || typeof v === "string")
                      .slice(0, 4)
                      .map(([k, v]) => ` · ${k.replace(/_/g, " ")} ${String(v)}`)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {missingConnection && <p className="text-xs text-warning">One or more steps need a connection. They will be skipped until you pick one.</p>}
        </div>

        <footer className="flex items-center gap-2 border-t border-border p-5">
          <label className="me-auto flex items-center gap-2 text-sm text-foreground">
            <input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))} /> Run on schedule
          </label>
          <button type="button" className="ui-btn-secondary" onClick={() => void save(true)} disabled={saving || draft.steps.length === 0}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} Save & run once
          </button>
          <button type="button" className="ui-btn-primary" onClick={() => void save(false)} disabled={saving || draft.steps.length === 0}>
            Save
          </button>
        </footer>
      </div>
    </div>
  );
}

function StepShell({ label, icon: Icon, children, onRemove }: { label: string; icon: LucideIcon; children: ReactNode; onRemove?: () => void }) {
  return (
    <section className="rounded-2xl border border-border bg-background p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="grid h-6 w-6 place-items-center rounded-md bg-brand/10 text-brand">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className="ui-kicker">{label}</span>
        {onRemove && (
          <button type="button" className="ui-btn-ghost ui-btn-sm ms-auto text-muted-foreground" onClick={onRemove} aria-label="Remove step">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function ScheduleEditor({ value, onChange }: { value: RoutineSchedule; onChange: (s: RoutineSchedule) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <select className="ui-input" value={value.kind} onChange={(e) => onChange({ ...value, kind: e.target.value as RoutineSchedule["kind"], seconds: e.target.value === "interval" ? value.seconds ?? 3600 : null, at: e.target.value === "interval" ? null : value.at ?? "09:00" })}>
        <option value="daily">Every day</option>
        <option value="weekly">Every week</option>
        <option value="interval">Every few hours</option>
      </select>
      {value.kind === "weekly" && (
        <select className="ui-input" value={value.weekday ?? 0} onChange={(e) => onChange({ ...value, weekday: Number(e.target.value) })}>
          {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((d, i) => (
            <option key={d} value={i}>
              {d}
            </option>
          ))}
        </select>
      )}
      {value.kind !== "interval" && (
        <>
          <span className="text-muted-foreground">at</span>
          <input type="time" className="ui-input" value={value.at ?? "09:00"} onChange={(e) => onChange({ ...value, at: e.target.value })} />
        </>
      )}
      {value.kind === "interval" && (
        <select className="ui-input" value={value.seconds ?? 3600} onChange={(e) => onChange({ ...value, seconds: Number(e.target.value) })}>
          <option value={900}>every 15 min</option>
          <option value={1800}>every 30 min</option>
          <option value={3600}>every hour</option>
          <option value={3 * 3600}>every 3 hours</option>
          <option value={6 * 3600}>every 6 hours</option>
          <option value={12 * 3600}>every 12 hours</option>
        </select>
      )}
      <span className="text-xs text-muted-foreground">Dubai time</span>
    </div>
  );
}

function ConnectionPicker({ spec, connections, value, onChange }: { spec: RoutineStepSpec; connections: Connection[]; value: string | null; onChange: (id: string | null) => void }) {
  const options = connections.filter((c) => !spec.capability || c.capabilities.includes(spec.capability));
  if (options.length === 0) {
    return (
      <p className="text-xs text-warning">
        No connection can do this yet.{" "}
        <a href="/cowork?tab=connections" className="underline">
          Add one in Connections
        </a>
        .
      </p>
    );
  }
  return (
    <label className="block text-xs">
      <span className="mb-1 block text-muted-foreground">Using</span>
      <select className="ui-input w-full" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">Choose a connection…</option>
        {options.map((c) => (
          <option key={c.id} value={c.id} disabled={c.status !== "active"}>
            {c.display_name} ({c.provider_name}){c.status !== "active" ? " — paused" : c.health !== "connected" ? ` — ${c.health.replace("_", " ")}` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

function ParamsEditor({
  spec,
  params,
  stages,
  jobs,
  onChange,
}: {
  spec: RoutineStepSpec;
  params: Record<string, unknown>;
  stages: string[];
  jobs: { id: string; label: string }[];
  onChange: (p: Record<string, unknown>) => void;
}) {
  const visible = spec.params.filter((p) => p !== "lead_ids" && p !== "path");
  if (visible.length === 0) return null;
  const set = (k: string, v: unknown) => onChange({ ...params, [k]: v === "" ? undefined : v });
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {visible.map((key) => {
        const val = params[key];
        const label = PARAM_LABEL[key] ?? key.replace(/_/g, " ");
        if (key === "band") {
          return (
            <Field key={key} label={label}>
              <select className="ui-input w-full" value={typeof val === "string" ? val : ""} onChange={(e) => set(key, e.target.value)}>
                <option value="">Any</option>
                <option value="hot">Hot</option>
                <option value="warm">Warm</option>
                <option value="cold">Cold</option>
              </select>
            </Field>
          );
        }
        if (key === "stage") {
          return (
            <Field key={key} label={label}>
              <select className="ui-input w-full" value={typeof val === "string" ? val : ""} onChange={(e) => set(key, e.target.value)}>
                <option value="">Any</option>
                {stages.map((s) => (
                  <option key={s} value={s}>
                    {s.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </Field>
          );
        }
        if (key === "job_id") {
          return (
            <Field key={key} label={label}>
              <select className="ui-input w-full" value={typeof val === "string" ? val : ""} onChange={(e) => set(key, e.target.value)}>
                <option value="">Choose…</option>
                {jobs.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.label}
                  </option>
                ))}
              </select>
            </Field>
          );
        }
        if (key === "channel") {
          return (
            <Field key={key} label={label}>
              <select className="ui-input w-full" value={typeof val === "string" ? val : "WhatsApp"} onChange={(e) => set(key, e.target.value)}>
                <option value="WhatsApp">WhatsApp text</option>
                <option value="voice">Voice note</option>
                <option value="email">E-mail</option>
              </select>
            </Field>
          );
        }
        if (key === "use_drafts") {
          return (
            <label key={key} className="flex items-center gap-2 pt-5 text-xs text-foreground">
              <input type="checkbox" checked={Boolean(val)} onChange={(e) => set(key, e.target.checked)} /> {label}
            </label>
          );
        }
        if (key === "metric") {
          return (
            <Field key={key} label={label}>
              <select className="ui-input w-full" value={typeof val === "string" ? val : ""} onChange={(e) => set(key, e.target.value)}>
                <option value="">From question</option>
                {["top_leads", "leads_for_area", "area_demand", "stale_leads", "source_mix", "pipeline", "score_changes", "new_leads", "viewings", "budget_bands"].map((m) => (
                  <option key={m} value={m}>
                    {m.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </Field>
          );
        }
        const numeric = /hours|limit|score|days/.test(key);
        const wide = /template|text|question|focus|title|subject/.test(key);
        return (
          <Field key={key} label={label} wide={wide}>
            <input
              className="ui-input w-full"
              type={numeric ? "number" : "text"}
              value={val == null ? "" : String(val)}
              onChange={(e) => set(key, numeric ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)}
              placeholder={key === "template" ? "Hi {first_name}, following up on {area}…" : ""}
            />
          </Field>
        );
      })}
    </div>
  );
}

function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`block text-xs ${wide ? "sm:col-span-2" : ""}`}>
      <span className="mb-1 block text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function StepPicker({
  catalog,
  kind,
  showAdvanced,
  onToggleAdvanced,
  onPick,
  onCancel,
}: {
  catalog: RoutineStepSpec[];
  kind: "source" | "action";
  showAdvanced: boolean;
  onToggleAdvanced: () => void;
  onPick: (type: string) => void;
  onCancel: () => void;
}) {
  const items = catalog.filter((s) => (kind === "source" ? SOURCE_TYPES.has(s.type) : !SOURCE_TYPES.has(s.type))).filter((s) => showAdvanced || !ADVANCED_TYPES.has(s.type));
  return (
    <div className="rounded-2xl border border-dashed border-border p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-medium text-foreground">{kind === "source" ? "Which leads or data?" : "What should happen?"}</p>
        <div className="flex items-center gap-2">
          <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={onToggleAdvanced}>
            {showAdvanced ? "Hide advanced" : "Show advanced"}
          </button>
          <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={onCancel} aria-label="Cancel">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {items.map((s) => {
          const Icon = GROUP_ICON[s.group];
          return (
            <button key={s.type} type="button" onClick={() => onPick(s.type)} className="flex items-start gap-2 rounded-xl border border-border bg-card p-3 text-start text-sm transition hover:border-brand/50 hover:bg-brand/[0.03]">
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
              <span className="text-foreground">{s.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
