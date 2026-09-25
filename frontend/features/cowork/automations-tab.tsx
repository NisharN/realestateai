"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, FlaskConical, Play, Plus, RefreshCw, Trash2, Zap } from "lucide-react";
import { Badge, EmptyState, Section, Skeleton } from "@/components/ui/page";
import {
  coworkApi,
  type Automation,
  type AutomationCatalog,
  type AutomationCondition,
  type AutomationInput,
  type AutomationRun,
} from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";
import type { Say } from "./ingestion-tools";
import { RunStatus, Toggle } from "./shared";

const EMPTY: AutomationInput = {
  name: "",
  description: "",
  trigger: "lead.scored",
  conditions: [],
  action: "notify_broker",
  action_params: {},
  enabled: true,
};

const PRESETS: { label: string; input: AutomationInput }[] = [
  {
    label: "Hot lead → task for broker",
    input: {
      name: "Hot lead follow-up task",
      description: "Create a 2-hour follow-up task whenever a lead scores hot.",
      trigger: "lead.scored",
      conditions: [{ field: "band", op: "eq", value: "hot" }],
      action: "create_task",
      action_params: { title: "Call hot lead within 2 hours", due_in_hours: 2 },
    },
  },
  {
    label: "Handoff → notify broker",
    input: {
      name: "Notify broker on handoff",
      description: "WhatsApp/notification to the assigned broker when a handoff is created.",
      trigger: "handoff.created",
      conditions: [],
      action: "notify_broker",
      action_params: { message: "New qualified lead handed to you — see Today." },
    },
  },
  {
    label: "Viewing confirmed → follow-ups",
    input: {
      name: "Post-viewing follow-ups",
      description: "Schedule the standard follow-up cadence after a confirmed viewing.",
      trigger: "viewing.confirmed",
      conditions: [],
      action: "schedule_followups",
      action_params: {},
    },
  },
];

export function AutomationsTab({ say }: { say: Say }) {
  const [catalog, setCatalog] = useState<AutomationCatalog | null>(null);
  const [rules, setRules] = useState<Automation[] | null>(null);
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [editing, setEditing] = useState<AutomationInput | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [preview, setPreview] = useState<Record<string, { checked: number; matched: number; sample: { id: string; name: string; stage: string | null; score: number | null }[] }>>({});
  const [processing, setProcessing] = useState(false);

  const load = useCallback(async () => {
    const [c, a, r] = await Promise.all([coworkApi.catalog(), coworkApi.automations(), coworkApi.automationRuns()]);
    if (c.data) setCatalog(c.data);
    if (a.data) setRules(a.data);
    else say(a, "");
    if (r.data) setRuns(r.data);
  }, [say]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    const r = editingId ? await coworkApi.patchAutomation(editingId, editing) : await coworkApi.createAutomation(editing);
    if (say(r, editingId ? "Automation updated" : "Automation created")) {
      setEditing(null);
      setEditingId(null);
      void load();
    }
  };

  const remove = async (id: string) => {
    if (say(await coworkApi.deleteAutomation(id), "Automation deleted")) void load();
  };

  const toggle = async (rule: Automation, enabled: boolean) => {
    if (say(await coworkApi.patchAutomation(rule.id, { enabled }), enabled ? "Enabled" : "Paused")) void load();
  };

  const test = async (id: string) => {
    const r = await coworkApi.testAutomation(id);
    if (r.data) setPreview((p) => ({ ...p, [id]: r.data! }));
    else say(r, "");
  };

  const processNow = async () => {
    setProcessing(true);
    const r = await coworkApi.runAutomations();
    setProcessing(false);
    if (say(r, `Processed pending events · ${r.data?.summary ? JSON.stringify(r.data.summary) : "done"}`)) void load();
  };

  if (!rules || !catalog) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          When something happens to a lead, do something — fixed, auditable triggers and actions. Follow-up cadence presets live in{" "}
          <Link href="/automations" className="inline-flex items-center gap-1 font-medium text-brand hover:underline">
            Playbooks <ArrowRight className="h-3 w-3" />
          </Link>
          .
        </p>
        <div className="flex items-center gap-2">
          <button type="button" className="ui-btn-secondary ui-btn-sm" disabled={processing} onClick={() => void processNow()}>
            {processing ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />} Process events now
          </button>
          <button
            type="button"
            className="ui-btn-primary ui-btn-sm"
            onClick={() => {
              setEditingId(null);
              setEditing({ ...EMPTY });
            }}
          >
            <Plus className="h-3.5 w-3.5" /> New automation
          </button>
        </div>
      </div>

      {editing && (
        <RuleEditor
          catalog={catalog}
          value={editing}
          onChange={setEditing}
          onCancel={() => {
            setEditing(null);
            setEditingId(null);
          }}
          onSubmit={save}
          isEdit={!!editingId}
        />
      )}

      {rules.length === 0 ? (
        <div className="space-y-4">
          <EmptyState title="No automations yet" body="Start from a preset or build your own trigger → action rule." icon={<Zap className="h-5 w-5" />} />
          <div className="grid gap-3 sm:grid-cols-3">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                className="ui-card p-4 text-start transition hover:border-brand/40 hover:shadow-lg"
                onClick={() => {
                  setEditingId(null);
                  setEditing({ ...p.input });
                }}
              >
                <p className="text-sm font-semibold text-foreground">{p.label}</p>
                <p className="mt-1 text-xs text-muted-foreground">{p.input.description}</p>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {rules.map((rule) => (
            <article key={rule.id} className={`ui-card p-4 ${rule.enabled ? "" : "opacity-70"}`}>
              <div className="flex flex-wrap items-start gap-4">
                <Toggle checked={rule.enabled} label={`Enable ${rule.name}`} onChange={(v) => void toggle(rule, v)} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-foreground">{rule.name}</p>
                    {rule.last_status && <RunStatus status={rule.last_status} />}
                  </div>
                  {rule.description && <p className="mt-0.5 text-xs text-muted-foreground">{rule.description}</p>}
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                    <Badge tone="brand">when {catalog.triggers[rule.trigger] ?? rule.trigger}</Badge>
                    {rule.conditions.map((c, i) => (
                      <Badge key={i} tone="neutral">
                        {c.field} {c.op} {String(c.value ?? "")}
                      </Badge>
                    ))}
                    <ArrowRight className="h-3 w-3 text-muted-foreground" />
                    <Badge tone="gold">{catalog.actions[rule.action] ?? rule.action}</Badge>
                  </div>
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    Fired {rule.run_count.toLocaleString("en-US")}× · last {rule.last_run_at ? relativeTime(rule.last_run_at) : "never"}
                  </p>
                  {preview[rule.id] && (
                    <div className="mt-2 rounded-lg bg-muted/60 p-2 text-xs">
                      <p className="font-medium text-foreground">
                        Dry run: {preview[rule.id].matched} of {preview[rule.id].checked} recent leads match
                      </p>
                      {preview[rule.id].sample.length > 0 && (
                        <p className="mt-1 text-muted-foreground">
                          {preview[rule.id].sample.slice(0, 5).map((s) => `${s.name}${s.score != null ? ` (${s.score})` : ""}`).join(", ")}
                        </p>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={() => void test(rule.id)} title="Dry run against recent leads">
                    <FlaskConical className="h-3.5 w-3.5" /> Test
                  </button>
                  <button
                    type="button"
                    className="ui-btn-ghost ui-btn-sm"
                    onClick={() => {
                      setEditingId(rule.id);
                      setEditing({
                        name: rule.name,
                        description: rule.description ?? "",
                        trigger: rule.trigger,
                        conditions: rule.conditions,
                        action: rule.action,
                        action_params: rule.action_params,
                        enabled: rule.enabled,
                      });
                    }}
                  >
                    Edit
                  </button>
                  <button type="button" className="ui-btn-ghost ui-btn-sm text-danger" aria-label={`Delete ${rule.name}`} onClick={() => void remove(rule.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      <Section title="Recent firings" count={runs.length}>
        {runs.length === 0 ? (
          <EmptyState title="Nothing fired yet" body="Automations fire as lead events arrive; use “Process events now” to run the consumer immediately." />
        ) : (
          <div className="-m-5 overflow-x-auto">
            <table className="ui-table w-full text-sm">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Automation</th>
                  <th>Event</th>
                  <th>Lead</th>
                  <th>Status</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td className="whitespace-nowrap text-muted-foreground">{relativeTime(r.created_at)}</td>
                    <td className="font-medium">{r.automation_name ?? r.automation_id}</td>
                    <td className="text-muted-foreground">{r.event_type ?? "—"}</td>
                    <td>
                      {r.lead_id ? (
                        <Link href={`/broker/leads/${r.lead_id}`} className="text-brand hover:underline">
                          {r.lead_id.slice(0, 8)}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <RunStatus status={r.status} />
                    </td>
                    <td className="max-w-xs truncate text-xs text-muted-foreground" title={r.error ?? JSON.stringify(r.result)}>
                      {r.error ? <span className="text-danger">{r.error}</span> : Object.keys(r.result).length ? JSON.stringify(r.result) : "—"}
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

function RuleEditor({
  catalog,
  value,
  onChange,
  onCancel,
  onSubmit,
  isEdit,
}: {
  catalog: AutomationCatalog;
  value: AutomationInput;
  onChange: (next: AutomationInput) => void;
  onCancel: () => void;
  onSubmit: (e: FormEvent) => void;
  isEdit: boolean;
}) {
  const setCond = (i: number, patch: Partial<AutomationCondition>) =>
    onChange({ ...value, conditions: value.conditions.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const setParam = (key: string, v: string | number) => onChange({ ...value, action_params: { ...value.action_params, [key]: v } });
  const param = (key: string) => {
    const v = value.action_params[key];
    return typeof v === "string" || typeof v === "number" ? String(v) : "";
  };

  return (
    <form onSubmit={onSubmit} className="ui-card space-y-5 border-brand/30 p-5">
      <div className="grid gap-4 md:grid-cols-2">
        <label className="block text-sm">
          <span className="ui-kicker">Name</span>
          <input required className="ui-input mt-1.5" value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} placeholder="Hot lead follow-up task" />
        </label>
        <label className="block text-sm">
          <span className="ui-kicker">Description</span>
          <input className="ui-input mt-1.5" value={value.description ?? ""} onChange={(e) => onChange({ ...value, description: e.target.value })} placeholder="Optional" />
        </label>
      </div>

      <div className="grid gap-4 md:grid-cols-[1fr_auto_1fr] md:items-start">
        <div>
          <p className="ui-kicker">When</p>
          <select className="ui-input mt-1.5" value={value.trigger} onChange={(e) => onChange({ ...value, trigger: e.target.value })}>
            {Object.entries(catalog.triggers).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
          <div className="mt-3 space-y-2">
            {value.conditions.map((c, i) => (
              <div key={i} className="flex items-center gap-2">
                <select className="ui-input h-9 flex-1 text-xs" value={c.field} onChange={(e) => setCond(i, { field: e.target.value })}>
                  {catalog.condition_fields.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
                <select className="ui-input h-9 w-24 text-xs" value={c.op} onChange={(e) => setCond(i, { op: e.target.value as AutomationCondition["op"] })}>
                  {catalog.operators.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
                {c.op !== "exists" && (
                  <input
                    className="ui-input h-9 flex-1 text-xs"
                    value={typeof c.value === "string" || typeof c.value === "number" ? String(c.value) : Array.isArray(c.value) ? c.value.join(",") : ""}
                    placeholder={c.op === "in" ? "a,b,c" : "value"}
                    onChange={(e) => {
                      const raw = e.target.value;
                      const num = Number(raw);
                      setCond(i, { value: c.op === "in" ? raw.split(",").map((s) => s.trim()) : raw !== "" && !Number.isNaN(num) ? num : raw });
                    }}
                  />
                )}
                <button type="button" className="ui-btn-ghost ui-btn-sm" aria-label="Remove condition" onClick={() => onChange({ ...value, conditions: value.conditions.filter((_, j) => j !== i) })}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            {value.conditions.length < 10 && (
              <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={() => onChange({ ...value, conditions: [...value.conditions, { field: catalog.condition_fields[0] ?? "band", op: "eq", value: "" }] })}>
                <Plus className="h-3.5 w-3.5" /> Add condition
              </button>
            )}
          </div>
        </div>

        <ArrowRight className="mt-9 hidden h-5 w-5 text-muted-foreground md:block" />

        <div>
          <p className="ui-kicker">Then</p>
          <select className="ui-input mt-1.5" value={value.action} onChange={(e) => onChange({ ...value, action: e.target.value, action_params: {} })}>
            {Object.entries(catalog.actions).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
          <div className="mt-3 space-y-2">
            {value.action === "create_task" && (
              <>
                <input className="ui-input h-9 text-xs" placeholder="Task title" value={param("title")} onChange={(e) => setParam("title", e.target.value)} />
                <input className="ui-input h-9 text-xs" type="number" min={1} placeholder="Due in hours (default 24)" value={param("due_in_hours")} onChange={(e) => setParam("due_in_hours", Number(e.target.value))} />
              </>
            )}
            {value.action === "notify_broker" && (
              <input className="ui-input h-9 text-xs" placeholder="Message to broker" value={param("message")} onChange={(e) => setParam("message", e.target.value)} />
            )}
            {value.action === "set_stage" && (
              <select className="ui-input h-9 text-xs" value={param("stage")} onChange={(e) => setParam("stage", e.target.value)}>
                <option value="">Choose a stage…</option>
                {catalog.stages.map((s) => (
                  <option key={s} value={s}>
                    {s.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            )}
            {value.action === "run_job" && (
              <select className="ui-input h-9 text-xs" value={param("job_id")} onChange={(e) => setParam("job_id", e.target.value)}>
                <option value="">Choose a job…</option>
                {catalog.jobs.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.label}
                  </option>
                ))}
              </select>
            )}
            {value.action === "schedule_followups" && <p className="text-xs text-muted-foreground">Uses the workspace follow-up cadence from Playbooks.</p>}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        <button type="button" className="ui-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="ui-btn-primary">
          {isEdit ? "Save changes" : "Create automation"}
        </button>
      </div>
    </form>
  );
}
