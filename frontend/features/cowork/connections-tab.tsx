"use client";

/**
 * Connections — where a broker plugs in the tools they already use.
 * Grouped by what the tool does for them (leads in, talking to leads, calendar, AI),
 * one card per connection with Test / Webhook test / Pause, and an inline setup
 * form driven by the provider catalog. Secrets are write-only: they never come back.
 */

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Bot,
  CalendarDays,
  Cable,
  CheckCircle2,
  Copy,
  Eye,
  EyeOff,
  Inbox,
  Loader2,
  MessageCircle,
  Mic,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  Webhook,
  X,
  type LucideIcon,
} from "lucide-react";
import { Badge, Skeleton, type BadgeTone } from "@/components/ui/page";
import { coworkApi, type Connection, type ConnectionHealth, type ProviderCategory, type ProviderSpec, type WebhookTestResult } from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";
import type { Say } from "./ingestion-tools";

const HEALTH_TONE: Record<ConnectionHealth, BadgeTone> = {
  connected: "success",
  degraded: "warning",
  not_configured: "neutral",
  paused: "neutral",
  error: "danger",
  untested: "brand",
};

const HEALTH_LABEL: Record<ConnectionHealth, string> = {
  connected: "Connected",
  degraded: "Needs attention",
  not_configured: "Setup incomplete",
  paused: "Paused",
  error: "Error",
  untested: "Not tested yet",
};

interface Group {
  id: string;
  title: string;
  blurb: string;
  icon: LucideIcon;
  match: (p: ProviderSpec) => boolean;
}

/** Grouped by the job the tool does for a broker, not by protocol. */
const GROUPS: Group[] = [
  {
    id: "leads",
    title: "Where my leads come from",
    blurb: "Portals, Meta ads, Gmail and your website. New enquiries land in your pipeline and get scored.",
    icon: Inbox,
    match: (p) => p.category === "portal" || p.category === "email",
  },
  {
    id: "talk",
    title: "How I talk to leads",
    blurb: "WhatsApp text and automated voice notes. Each is its own connection — voice never falls back to text.",
    icon: MessageCircle,
    match: (p) => p.category === "messaging" && p.id !== "slack",
  },
  {
    id: "calendar",
    title: "Viewings & calendar",
    blurb: "Confirmed viewings go straight into your calendar.",
    icon: CalendarDays,
    match: (p) => p.category === "calendar",
  },
  {
    id: "ai",
    title: "AI",
    blurb: "Lead scoring and drafting. Works without a key using built-in rules; add one for Jev-quality scoring.",
    icon: Bot,
    match: (p) => p.category === "ai",
  },
  {
    id: "more",
    title: "More tools",
    blurb: "Team notifications and spreadsheets. Optional.",
    icon: Cable,
    match: (p) => p.id === "slack" || p.category === "data",
  },
];

const PROVIDER_ICON: Partial<Record<string, LucideIcon>> = { voice_notes: Mic, whatsapp: MessageCircle, google_calendar: CalendarDays };

export function ConnectionsTab({ say, categories, title, intro }: { say: Say; categories?: ProviderCategory[]; title?: string; intro?: string }) {
  const [catalog, setCatalog] = useState<ProviderSpec[] | null>(null);
  const [connections, setConnections] = useState<Connection[] | null>(null);
  const [adding, setAdding] = useState<ProviderSpec | null>(null);
  const [editing, setEditing] = useState<Connection | null>(null);

  const load = useCallback(async () => {
    const [cat, conns] = await Promise.all([coworkApi.providerCatalog(), coworkApi.connections()]);
    if (cat.data) setCatalog(cat.data);
    else say(cat, "");
    if (conns.data) setConnections(conns.data.connections);
    else say(conns, "");
  }, [say]);

  useEffect(() => {
    void load();
  }, [load]);

  const providers = useMemo(() => (catalog ?? []).filter((p) => !categories || categories.includes(p.category)), [catalog, categories]);
  const groups = useMemo(() => {
    if (categories) return [{ id: "all", title: title ?? "Connections", blurb: intro ?? "", icon: Cable, match: () => true } satisfies Group];
    return GROUPS;
  }, [categories, title, intro]);

  if (!catalog || !connections) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-36" />
        ))}
      </div>
    );
  }

  const connected = connections.filter((c) => c.health === "connected").length;

  return (
    <div className="space-y-10">
      {!categories && (
        <p className="text-sm text-muted-foreground">
          {connections.length === 0 ? "Nothing connected yet. Start with where your leads come from." : `${connected} of ${connections.length} connections healthy.`}
        </p>
      )}

      {groups.map((g) => {
        const specs = providers.filter(g.match);
        if (specs.length === 0) return null;
        const Icon = g.icon;
        const mine = connections.filter((c) => specs.some((s) => s.id === c.provider));
        return (
          <section key={g.id} aria-labelledby={`grp-${g.id}`}>
            <div className="mb-3 flex items-start gap-3">
              <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-muted text-foreground/70">
                <Icon className="h-4 w-4" />
              </span>
              <div>
                <h2 id={`grp-${g.id}`} className="text-base font-semibold text-foreground">
                  {g.title}
                </h2>
                {g.blurb && <p className="text-sm text-muted-foreground">{g.blurb}</p>}
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {mine.map((c) => (
                <ConnectionCard key={c.id} connection={c} spec={specs.find((s) => s.id === c.provider)} say={say} onChanged={load} onEdit={() => setEditing(c)} />
              ))}
              {specs.map((spec) => (
                <button
                  key={spec.id}
                  type="button"
                  onClick={() => setAdding(spec)}
                  className="ui-card flex min-h-[7rem] flex-col items-start gap-1.5 border-dashed p-4 text-start transition hover:border-brand/50 hover:bg-brand/[0.03]"
                >
                  <span className="flex w-full items-center justify-between">
                    <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <ProviderGlyph id={spec.id} />
                      {spec.name}
                    </span>
                    <Plus className="h-4 w-4 text-muted-foreground" />
                  </span>
                  <span className="line-clamp-2 text-xs text-muted-foreground">{spec.description}</span>
                  {spec.certification && <Badge tone="gold">{spec.certification}</Badge>}
                </button>
              ))}
            </div>
          </section>
        );
      })}

      {adding && (
        <SetupDrawer
          spec={adding}
          onClose={() => setAdding(null)}
          onSaved={() => {
            setAdding(null);
            void load();
          }}
          say={say}
        />
      )}
      {editing && (
        <SetupDrawer
          spec={catalog.find((p) => p.id === editing.provider)!}
          existing={editing}
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

function ProviderGlyph({ id }: { id: string }) {
  const Icon = PROVIDER_ICON[id] ?? Cable;
  return <Icon className="h-4 w-4 text-brand" aria-hidden />;
}

function ConnectionCard({ connection: c, spec, say, onChanged, onEdit }: { connection: Connection; spec?: ProviderSpec; say: Say; onChanged: () => void; onEdit: () => void }) {
  const [busy, setBusy] = useState<"test" | "webhook" | "toggle" | "delete" | null>(null);
  const [webhook, setWebhook] = useState<WebhookTestResult | null>(null);
  const [reveal, setReveal] = useState<{ url: string; secret: string; signature_header: string } | null>(null);

  const test = async () => {
    setBusy("test");
    const r = await coworkApi.testConnection(c.id);
    say(r, r.data ? `${c.display_name}: ${r.data.detail}` : "");
    setBusy(null);
    onChanged();
  };

  const testWebhook = async () => {
    setBusy("webhook");
    const r = await coworkApi.testWebhook(c.id);
    if (r.data) setWebhook(r.data);
    say(r, r.data ? `Webhook test: ${r.data.detail}` : "");
    setBusy(null);
    onChanged();
  };

  const toggle = async () => {
    setBusy("toggle");
    say(await coworkApi.patchConnection(c.id, { enabled: c.status !== "active" }), c.status === "active" ? "Paused" : "Resumed");
    setBusy(null);
    onChanged();
  };

  const remove = async () => {
    if (!window.confirm(`Remove ${c.display_name}? Routines using it will skip this step.`)) return;
    setBusy("delete");
    say(await coworkApi.deleteConnection(c.id), "Connection removed");
    setBusy(null);
    onChanged();
  };

  const showWebhook = async () => {
    if (reveal) return setReveal(null);
    const r = await coworkApi.revealWebhook(c.id);
    if (r.data) setReveal(r.data);
    else say(r, "");
  };

  return (
    <article className="ui-card flex flex-col gap-3 p-4">
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <ProviderGlyph id={c.provider} />
            <span className="truncate">{c.display_name}</span>
          </p>
          <p className="text-xs text-muted-foreground">{c.provider_name}</p>
        </div>
        <Badge tone={HEALTH_TONE[c.health]}>{HEALTH_LABEL[c.health]}</Badge>
      </header>

      {c.missing.length > 0 && (
        <p className="text-xs text-warning">Missing: {c.missing.map((m) => spec?.fields.find((f) => f.key === m)?.label ?? m).join(", ")}</p>
      )}
      {c.last_error && c.health === "error" && <p className="line-clamp-2 text-xs text-danger">{c.last_error}</p>}

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <dt>Last test</dt>
        <dd className="text-end text-foreground/80">{c.last_test_at ? `${c.last_test_status} · ${relativeTime(c.last_test_at)}` : "never"}</dd>
        <dt>Activity</dt>
        <dd className="text-end text-foreground/80">{c.last_activity_at ? relativeTime(c.last_activity_at) : "—"}</dd>
        {c.inbound_webhook && (
          <>
            <dt>Received</dt>
            <dd className="text-end tabular-nums text-foreground/80">{c.received_total}</dd>
          </>
        )}
      </dl>

      {reveal && (
        <div className="space-y-1 rounded-lg bg-muted p-2 text-xs">
          <CopyRow label="URL" value={reveal.url} />
          <CopyRow label={reveal.signature_header} value={reveal.secret} secret />
        </div>
      )}
      {webhook && (
        <p className={`rounded-lg p-2 text-xs ${webhook.status === "ok" ? "bg-success-soft text-success" : "bg-danger-soft text-danger"}`}>
          {webhook.status === "ok" ? <CheckCircle2 className="me-1 inline h-3.5 w-3.5" /> : <X className="me-1 inline h-3.5 w-3.5" />}
          {webhook.detail}
          {webhook.count != null && ` · ${webhook.count} lead(s) parsed`}
        </p>
      )}

      <footer className="mt-auto flex flex-wrap items-center gap-1.5">
        <button type="button" className="ui-btn-secondary ui-btn-sm" onClick={test} disabled={busy !== null}>
          {busy === "test" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />} Test
        </button>
        {c.inbound_webhook && (
          <>
            <button type="button" className="ui-btn-secondary ui-btn-sm" onClick={testWebhook} disabled={busy !== null}>
              {busy === "webhook" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Webhook className="h-3.5 w-3.5" />} Test webhook
            </button>
            <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={showWebhook} aria-label="Show webhook URL and secret">
              {reveal ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </>
        )}
        <span className="ms-auto flex items-center gap-1">
          <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={onEdit} aria-label="Edit connection">
            Edit
          </button>
          <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={toggle} disabled={busy !== null} aria-label={c.status === "active" ? "Pause" : "Resume"}>
            {c.status === "active" ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          </button>
          <button type="button" className="ui-btn-ghost ui-btn-sm text-danger" onClick={remove} disabled={busy !== null} aria-label="Remove connection">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </span>
      </footer>
    </article>
  );
}

function CopyRow({ label, value, secret = false }: { label: string; value: string; secret?: boolean }) {
  const [shown, setShown] = useState(!secret);
  return (
    <div className="flex items-center gap-2">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground">{shown ? value : "•".repeat(24)}</code>
      {secret && (
        <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={() => setShown((s) => !s)} aria-label={shown ? "Hide" : "Show"}>
          {shown ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
        </button>
      )}
      <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={() => void navigator.clipboard?.writeText(value)} aria-label={`Copy ${label}`}>
        <Copy className="h-3 w-3" />
      </button>
    </div>
  );
}

function SetupDrawer({ spec, existing, onClose, onSaved, say }: { spec: ProviderSpec; existing?: Connection; onClose: () => void; onSaved: () => void; say: Say }) {
  const [name, setName] = useState(existing?.display_name ?? spec.name);
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of spec.fields) init[f.key] = f.secret ? "" : existing?.config[f.key] ?? "";
    return init;
  });
  const [shown, setShown] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [testAfter, setTestAfter] = useState(true);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    const config: Record<string, string> = {};
    for (const f of spec.fields) {
      const v = values[f.key]?.trim();
      if (v) config[f.key] = v;
    }
    const r = existing ? await coworkApi.patchConnection(existing.id, { display_name: name, config }) : await coworkApi.createConnection({ provider: spec.id, display_name: name, config });
    if (r.data && testAfter) {
      const t = await coworkApi.testConnection(r.data.id);
      say(t, t.data ? `${name}: ${t.data.detail}` : "");
    } else {
      say(r, existing ? "Connection updated" : "Connection added");
    }
    setSaving(false);
    if (r.data) onSaved();
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" role="dialog" aria-modal="true" aria-labelledby="setup-title" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="flex h-full w-full max-w-md flex-col overflow-y-auto bg-card shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-border p-5">
          <div>
            <p className="ui-kicker">{existing ? "Edit connection" : "Connect"}</p>
            <h2 id="setup-title" className="text-lg font-semibold text-foreground">
              {spec.name}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">{spec.description}</p>
            {spec.docs_url && (
              <a href={spec.docs_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs text-brand hover:underline">
                Where to find these details ↗
              </a>
            )}
          </div>
          <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 space-y-4 p-5">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-foreground">Name</span>
            <input className="ui-input w-full" value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} />
          </label>
          {spec.fields.map((f) => (
            <label key={f.key} className="block">
              <span className="mb-1 flex items-center justify-between text-xs font-medium text-foreground">
                {f.label}
                {!f.required && <span className="font-normal text-muted-foreground">optional</span>}
              </span>
              <span className="relative block">
                <input
                  className="ui-input w-full pe-9"
                  type={f.secret && !shown[f.key] ? "password" : "text"}
                  value={values[f.key] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  placeholder={f.secret && existing?.config[f.key] ? "Saved — leave blank to keep" : f.placeholder}
                  required={f.required && !(f.secret && existing?.config[f.key])}
                  autoComplete="off"
                  spellCheck={false}
                />
                {f.secret && (
                  <button type="button" className="absolute inset-y-0 end-2 my-auto text-muted-foreground" onClick={() => setShown((s) => ({ ...s, [f.key]: !s[f.key] }))} aria-label={shown[f.key] ? "Hide" : "Show"}>
                    {shown[f.key] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                )}
              </span>
              {f.help && <span className="mt-1 block text-xs text-muted-foreground">{f.help}</span>}
            </label>
          ))}
          {spec.inbound_webhook && (
            <p className="rounded-lg bg-muted p-3 text-xs text-muted-foreground">
              <Webhook className="me-1 inline h-3.5 w-3.5" />
              After saving you get a webhook URL and signing secret to paste into {spec.name}. Every delivery is verified before it touches your pipeline.
            </p>
          )}
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input type="checkbox" checked={testAfter} onChange={(e) => setTestAfter(e.target.checked)} /> Test the connection right after saving
          </label>
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-border p-5">
          <button type="button" className="ui-btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="ui-btn-primary" disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null} {existing ? "Save" : "Connect"}
          </button>
        </footer>
      </form>
    </div>
  );
}
