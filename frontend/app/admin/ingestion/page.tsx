"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import type { ApiResponse } from "@/lib/api";
import {
  adminApi,
  type Connector,
  type CsvUploadResult,
  type DataHealth,
  type FieldMapEntry,
  type OpsOverview,
  type ReviewItem,
  type TurnStats,
} from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";

const CONNECTOR_TYPES = [
  ["csv_upload", "CSV upload"],
  ["webhook", "Webhook (push)"],
  ["generic_crm", "Generic CRM (pull JSON)"],
  ["hubspot", "HubSpot (pull)"],
  ["zoho", "Zoho (pull)"],
  ["salesforce", "Salesforce (pull)"],
  ["bitrix24", "Bitrix24 (pull)"],
  ["manual", "Manual"],
] as const;

const PULL_TYPES = new Set(["generic_crm", "hubspot", "zoho", "salesforce", "bitrix24"]);

/** Mirrors CANONICAL_FIELDS in backend/app/modules/ingestion/models.py. */
const TARGET_FIELDS = [
  "", "first_name", "last_name", "full_name", "phone", "email", "message", "budget", "budget_min", "budget_max",
  "area", "property_type", "bedrooms", "purpose", "timeline", "payment", "language", "source",
  "listing_ref", "external_id", "created_at", "consent",
];

type Tab = "connectors" | "csv" | "review" | "health" | "ops";

export default function IngestionAdminPage() {
  const [tab, setTab] = useState<Tab>("connectors");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const say = useCallback((result: ApiResponse<unknown>, ok: string) => {
    if (result.error) {
      setError(result.error);
      setMessage(null);
    } else {
      setError(null);
      setMessage(ok);
    }
    return !result.error;
  }, []);

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-8">
      <div className="mx-auto max-w-6xl">
        <h1 className="text-3xl font-semibold">Lead ingestion</h1>
        <p className="mt-1 text-slate-600">Connect CRMs, upload CSVs, fix records that failed validation, and watch pipeline health.</p>

        <div role="tablist" className="mt-6 flex gap-1 rounded-xl bg-slate-200/70 p-1 text-sm font-medium">
          {(
            [
              ["connectors", "Connectors"],
              ["csv", "CSV upload"],
              ["review", "Review queue"],
              ["health", "Data health"],
              ["ops", "Ops"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={`flex-1 rounded-lg px-3 py-2 ${tab === key ? "bg-white shadow-sm" : "text-slate-600 hover:text-slate-900"}`}
            >
              {label}
            </button>
          ))}
        </div>

        {error && <p role="alert" className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {message && <p role="status" className="mt-4 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{message}</p>}

        <div className="mt-6">
          {tab === "connectors" && <ConnectorsTab say={say} />}
          {tab === "csv" && <CsvTab say={say} />}
          {tab === "review" && <ReviewTab say={say} />}
          {tab === "health" && <HealthTab say={say} />}
          {tab === "ops" && <OpsTab say={say} />}
        </div>
      </div>
    </main>
  );
}

type Say = (result: ApiResponse<unknown>, ok: string) => boolean;

function ConnectorsTab({ say }: { say: Say }) {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [type, setType] = useState<string>("webhook");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [credential, setCredential] = useState("");
  const [recordsPath, setRecordsPath] = useState("");
  const [cursorParam, setCursorParam] = useState("updated_after");
  const [cursorField, setCursorField] = useState("updated_at");
  const [schedule, setSchedule] = useState("300");
  const [mapping, setMapping] = useState<{ id: string; approved: FieldMapEntry[]; suggested: FieldMapEntry[] } | null>(null);

  const load = useCallback(async () => {
    const r = await adminApi.connectors();
    if (r.data) setConnectors(r.data);
    else if (r.error) say(r, "");
  }, [say]);

  useEffect(() => {
    void load();
  }, [load]);

  const isPull = PULL_TYPES.has(type);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    const config: Record<string, unknown> = {};
    if (isPull) {
      config.url = url;
      if (recordsPath) config.records_path = recordsPath;
      if (cursorParam) config.cursor_param = cursorParam;
      if (cursorField) config.cursor_field = cursorField;
    }
    const r = await adminApi.createConnector({
      type,
      display_name: name || undefined,
      schedule_seconds: isPull ? Number(schedule) : undefined,
      config,
      credential: isPull && credential ? credential : undefined,
    });
    if (say(r, r.data?.type === "webhook" ? "Webhook created — copy the signing secret now; it will not be shown again." : "Connector created.")) {
      if (r.data?.secret) setRevealed((s) => ({ ...s, [r.data!.id]: r.data!.secret! }));
      setName("");
      setUrl("");
      setCredential("");
      void load();
    }
  };

  const patch = async (c: Connector, body: Parameters<typeof adminApi.patchConnector>[1], ok: string) => {
    const r = await adminApi.patchConnector(c.id, body);
    if (say(r, ok)) {
      if (r.data?.secret) setRevealed((s) => ({ ...s, [c.id]: r.data!.secret! }));
      void load();
    }
  };

  const run = async (c: Connector) => {
    const r = await adminApi.runConnector(c.id);
    say(r, r.data ? `Pulled ${r.data.fetched ?? 0}, landed ${r.data.landed ?? 0}, published ${r.data.published}.` : "");
    void load();
  };

  const openMapping = async (c: Connector) => {
    const r = await adminApi.fieldMap(c.id);
    if (r.data) setMapping({ id: c.id, approved: r.data.approved, suggested: r.data.suggested });
    else say(r, "");
  };

  return (
    <div className="grid gap-6">
      <form onSubmit={create} className="grid gap-3 rounded-2xl border bg-white p-5 md:grid-cols-2">
        <h2 className="md:col-span-2 text-sm font-semibold uppercase tracking-wide text-slate-600">Add connector</h2>
        <select aria-label="Connector type" value={type} onChange={(e) => setType(e.target.value)} className="rounded-xl border px-4 py-3">
          {CONNECTOR_TYPES.map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <input aria-label="Display name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Display name (optional)" className="rounded-xl border px-4 py-3" />
        {isPull && (
          <>
            <input aria-label="CRM URL" type="url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://crm.example.com/api/leads" className="rounded-xl border px-4 py-3 md:col-span-2" />
            <input aria-label="API token" type="password" value={credential} onChange={(e) => setCredential(e.target.value)} placeholder="API token (sent as Bearer; stored, never shown again)" className="rounded-xl border px-4 py-3" autoComplete="off" />
            <input aria-label="Records path" value={recordsPath} onChange={(e) => setRecordsPath(e.target.value)} placeholder="Records path in response, e.g. data.items" className="rounded-xl border px-4 py-3" />
            <input aria-label="Cursor query param" value={cursorParam} onChange={(e) => setCursorParam(e.target.value)} placeholder="Cursor query param" className="rounded-xl border px-4 py-3" />
            <input aria-label="Cursor field" value={cursorField} onChange={(e) => setCursorField(e.target.value)} placeholder="Record field used as cursor" className="rounded-xl border px-4 py-3" />
            <label className="flex items-center gap-2 text-sm text-slate-600">
              Poll every
              <input aria-label="Schedule seconds" type="number" min={60} max={86400} value={schedule} onChange={(e) => setSchedule(e.target.value)} className="w-28 rounded-xl border px-3 py-2" />
              seconds
            </label>
          </>
        )}
        <button className="rounded-xl bg-slate-950 px-5 py-3 font-semibold text-white md:col-start-2 md:justify-self-end">Create</button>
      </form>

      <div className="overflow-hidden rounded-2xl border bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-100">
            <tr>
              <th className="p-3">Connector</th>
              <th className="p-3">Mode</th>
              <th className="p-3">Status</th>
              <th className="p-3">Last run</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {connectors.length === 0 && (
              <tr><td colSpan={5} className="p-4 text-slate-500">No connectors yet.</td></tr>
            )}
            {connectors.map((c) => (
              <tr key={c.id} className="border-t align-top">
                <td className="p-3">
                  <p className="font-medium">{c.display_name}</p>
                  <p className="text-xs text-slate-500">{c.type} · <span className="font-mono">{c.id}</span></p>
                  {c.webhook_path && <p className="mt-1 font-mono text-xs text-slate-600">POST {c.webhook_path}</p>}
                  {revealed[c.id] && (
                    <p className="mt-1 break-all rounded bg-amber-50 p-2 font-mono text-xs text-amber-900">secret: {revealed[c.id]}</p>
                  )}
                  {c.last_error && <p className="mt-1 text-xs text-red-600">{c.last_error}</p>}
                </td>
                <td className="p-3">{c.mode}{c.mode === "pull" && c.schedule_seconds ? ` / ${c.schedule_seconds}s` : ""}</td>
                <td className="p-3">
                  <span className="capitalize">{c.status}</span>
                  {c.consecutive_failures > 0 && <span className="ml-1 text-xs text-red-600">({c.consecutive_failures} failures)</span>}
                </td>
                <td className="p-3 text-xs text-slate-600">
                  {relativeTime(c.last_run_at)}
                  {c.last_success_at && <p className="text-slate-400">ok {relativeTime(c.last_success_at)}</p>}
                </td>
                <td className="p-3">
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    {c.mode === "pull" && (
                      <button onClick={() => run(c)} className="rounded-lg bg-slate-950 px-2.5 py-1 font-semibold text-white">Run now</button>
                    )}
                    <button onClick={() => openMapping(c)} className="rounded-lg border px-2.5 py-1">Field map</button>
                    {c.type === "webhook" && (
                      <button onClick={() => patch(c, { rotate_secret: true }, "Secret rotated — update the sender.")} className="rounded-lg border px-2.5 py-1">Rotate secret</button>
                    )}
                    {c.status === "active" ? (
                      <button onClick={() => patch(c, { status: "paused" }, "Connector paused.")} className="rounded-lg border px-2.5 py-1">Pause</button>
                    ) : (
                      <button onClick={() => patch(c, { status: "active" }, "Connector re-enabled.")} className="rounded-lg border px-2.5 py-1">Activate</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {mapping && (
        <FieldMapEditor
          mapping={mapping}
          onClose={() => setMapping(null)}
          onSave={async (entries) => {
            const r = await adminApi.putFieldMap(mapping.id, entries);
            if (say(r, `Field map approved (${r.data?.approved ?? 0} fields).`)) setMapping(null);
          }}
        />
      )}
    </div>
  );
}

function FieldMapEditor({
  mapping,
  onClose,
  onSave,
}: {
  mapping: { id: string; approved: FieldMapEntry[]; suggested: FieldMapEntry[] };
  onClose: () => void;
  onSave: (entries: FieldMapEntry[]) => Promise<void>;
}) {
  const initial = (() => {
    const bySource = new Map<string, FieldMapEntry>();
    for (const s of mapping.suggested) bySource.set(s.source_field, s);
    for (const a of mapping.approved) bySource.set(a.source_field, { ...bySource.get(a.source_field), ...a });
    return Array.from(bySource.values());
  })();
  const [rows, setRows] = useState<FieldMapEntry[]>(initial);

  if (rows.length === 0) {
    return (
      <section className="rounded-2xl border bg-white p-5 text-sm">
        <p className="text-slate-600">No records have arrived on this connector yet, so there is nothing to map. Upload or push a sample first.</p>
        <button onClick={onClose} className="mt-3 rounded-lg border px-3 py-1.5 text-xs">Close</button>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border bg-white p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Field map · <span className="font-mono normal-case">{mapping.id}</span></h2>
      <p className="mt-1 text-xs text-slate-500">Suggestions come from header names and sample values. Approve to apply on the next run; unmapped columns are kept in the lead&apos;s extra data.</p>
      <table className="mt-3 w-full text-sm">
        <thead className="text-left text-xs uppercase text-slate-500">
          <tr><th className="py-1">Source column</th><th className="py-1">Target field</th><th className="py-1">Confidence</th></tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.source_field} className="border-t">
              <td className="py-2 font-mono text-xs">{row.source_field}</td>
              <td className="py-2">
                <select
                  aria-label={`Target for ${row.source_field}`}
                  value={row.target_field ?? ""}
                  onChange={(e) => setRows(rows.map((r, j) => (j === i ? { ...r, target_field: e.target.value || null } : r)))}
                  className="rounded-lg border px-2 py-1"
                >
                  {TARGET_FIELDS.map((t) => <option key={t} value={t}>{t || "— ignore —"}</option>)}
                </select>
              </td>
              <td className="py-2 text-xs text-slate-500">{row.approved_at ? "approved" : row.confidence != null ? `${Math.round(row.confidence * 100)}%` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-4 flex gap-2">
        <button onClick={() => onSave(rows)} className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white">Approve mapping</button>
        <button onClick={onClose} className="rounded-xl border px-4 py-2 text-sm">Cancel</button>
      </div>
    </section>
  );
}

function CsvTab({ say }: { say: Say }) {
  const [file, setFile] = useState<File | null>(null);
  const [connectorId, setConnectorId] = useState("");
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [result, setResult] = useState<CsvUploadResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    adminApi.connectors().then((r) => r.data && setConnectors(r.data.filter((c) => c.type === "csv_upload")));
  }, []);

  const upload = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    const r = await adminApi.uploadCsv(file, connectorId || undefined);
    setBusy(false);
    if (say(r, `Landed ${r.data?.landed ?? 0} rows (${r.data?.duplicates ?? 0} duplicates skipped).`)) setResult(r.data ?? null);
  };

  return (
    <div className="grid gap-6">
      <form onSubmit={upload} className="grid gap-3 rounded-2xl border bg-white p-5 md:grid-cols-[1fr_260px_auto]">
        <input aria-label="CSV file" type="file" accept=".csv,text/csv" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="rounded-xl border px-4 py-2.5" />
        <select aria-label="CSV connector" value={connectorId} onChange={(e) => setConnectorId(e.target.value)} className="rounded-xl border px-4 py-3">
          <option value="">New upload connector (per file)</option>
          {connectors.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
        </select>
        <button disabled={busy || !file} className="rounded-xl bg-slate-950 px-5 py-3 font-semibold text-white disabled:opacity-50">
          {busy ? "Uploading…" : "Upload & process"}
        </button>
        <p className="text-xs text-slate-500 md:col-span-3">
          Re-uploading the same file creates zero new leads. Pick an existing connector to reuse its approved field map; phone or email is required for each row.
        </p>
      </form>

      {result && (
        <section className="rounded-2xl border bg-white p-5 text-sm">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Upload result</h2>
          <dl className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-6">
            {(
              [
                ["Rows", result.rows],
                ["Landed", result.landed],
                ["Duplicates", result.duplicates],
                ["Published", result.published],
                ["New leads", result.created],
                ["Needs review", result.review],
              ] as const
            ).map(([k, v]) => (
              <div key={k} className="rounded-xl bg-slate-50 p-3">
                <dt className="text-xs uppercase text-slate-500">{k}</dt>
                <dd className="text-xl font-semibold">{v}</dd>
              </div>
            ))}
          </dl>
          {result.field_map_suggestions.length > 0 && (
            <>
              <h3 className="mt-4 text-xs font-semibold uppercase text-slate-500">Detected columns</h3>
              <ul className="mt-1 grid gap-1 sm:grid-cols-2">
                {result.field_map_suggestions.map((s) => (
                  <li key={s.source_field} className="flex justify-between rounded-lg border px-3 py-1.5 text-xs">
                    <span className="font-mono">{s.source_field}</span>
                    <span className="text-slate-600">→ {s.target_field ?? "unmapped"}{s.confidence != null ? ` (${Math.round(s.confidence * 100)}%)` : ""}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-slate-500">Adjust under Connectors → Field map for connector <span className="font-mono">{result.connector_id}</span>.</p>
            </>
          )}
        </section>
      )}
    </div>
  );
}

function ReviewTab({ say }: { say: Say }) {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [showResolved, setShowResolved] = useState(false);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);

  const load = useCallback(async () => {
    const r = await adminApi.reviewQueue(showResolved);
    if (r.data) setItems(r.data);
    else if (r.error) say(r, "");
  }, [showResolved, say]);

  useEffect(() => {
    void load();
  }, [load]);

  const resolve = async (item: ReviewItem, action: "retry" | "discard", fixed?: Record<string, unknown>) => {
    const r = await adminApi.resolveReview(item.id, { action, fixed_payload: fixed });
    if (say(r, action === "discard" ? "Record discarded." : `Reprocessed: ${r.data?.status}${r.data?.lead_id ? ` → lead ${r.data.lead_id}` : ""}.`)) {
      setEditing(null);
      void load();
    }
  };

  const retryAll = async () => {
    const r = await adminApi.retryErrors();
    say(r, `Retried ${r.data?.retried ?? 0} errored records, ${r.data?.published ?? 0} published.`);
    void load();
  };

  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between text-sm">
        <label className="flex items-center gap-2 text-slate-600">
          <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /> Show resolved
        </label>
        <button onClick={retryAll} className="rounded-lg border bg-white px-3 py-1.5 text-xs font-semibold">Retry errored records</button>
      </div>
      {items.length === 0 && <p className="rounded-2xl border bg-white p-5 text-sm text-slate-500">Review queue is empty.</p>}
      {items.map((item) => (
        <article key={item.id} className="rounded-2xl border bg-white p-5 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-medium text-red-700">{item.reason}</p>
              <p className="text-xs text-slate-500">
                raw {item.raw_record_id} · {item.record_status ?? "?"} · {relativeTime(item.created_at)}
                {item.resolved_at ? ` · resolved ${relativeTime(item.resolved_at)}` : ""}
              </p>
            </div>
            {!item.resolved_at && (
              <div className="flex gap-1.5 text-xs">
                <button onClick={() => resolve(item, "retry")} className="rounded-lg bg-slate-950 px-2.5 py-1 font-semibold text-white">Retry as-is</button>
                <button onClick={() => setEditing({ id: item.id, text: JSON.stringify(item.payload ?? {}, null, 2) })} className="rounded-lg border px-2.5 py-1">Fix & retry</button>
                <button onClick={() => resolve(item, "discard")} className="rounded-lg border px-2.5 py-1 text-red-700">Discard</button>
              </div>
            )}
          </div>
          {item.suggested_fix && Object.keys(item.suggested_fix).length > 0 && (
            <p className="mt-2 text-xs text-slate-600">Suggested: {JSON.stringify(item.suggested_fix)}</p>
          )}
          {editing?.id === item.id ? (
            <div className="mt-3 grid gap-2">
              <textarea aria-label="Fixed payload" value={editing.text} onChange={(e) => setEditing({ id: item.id, text: e.target.value })} rows={8} className="w-full rounded-lg border p-2 font-mono text-xs" />
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    try {
                      resolve(item, "retry", JSON.parse(editing.text));
                    } catch {
                      say({ error: "Fixed payload must be valid JSON" }, "");
                    }
                  }}
                  className="rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white"
                >
                  Save & reprocess
                </button>
                <button onClick={() => setEditing(null)} className="rounded-lg border px-3 py-1.5 text-xs">Cancel</button>
              </div>
            </div>
          ) : (
            <pre className="mt-3 max-h-40 overflow-auto rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-700">{JSON.stringify(item.payload ?? {}, null, 2)}</pre>
          )}
        </article>
      ))}
    </div>
  );
}

function HealthTab({ say }: { say: Say }) {
  const [health, setHealth] = useState<DataHealth | null>(null);

  useEffect(() => {
    adminApi.dataHealth().then((r) => (r.data ? setHealth(r.data) : say(r, "")));
  }, [say]);

  if (!health) return <p role="status" className="text-sm text-slate-500">Loading…</p>;

  const stages = ["landed", "mapped", "cleaned", "validated", "merged", "enriched", "published", "review", "error"];

  return (
    <div className="grid gap-6">
      <div className="grid grid-cols-3 gap-3 md:grid-cols-9">
        {stages.map((s) => (
          <div key={s} className={`rounded-xl border bg-white p-3 ${s === "error" && health.totals[s] ? "border-red-300" : ""}`}>
            <p className="text-[10px] uppercase tracking-wide text-slate-500">{s}</p>
            <p className="text-xl font-semibold">{health.totals[s] ?? 0}</p>
          </div>
        ))}
      </div>
      <p className="text-sm text-slate-600">
        {health.review_open} open review items · {health.events_total} lead events emitted
      </p>
      <div className="overflow-hidden rounded-2xl border bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-100">
            <tr>
              <th className="p-3">Connector</th>
              <th className="p-3">Status</th>
              <th className="p-3">Records</th>
              <th className="p-3">Published</th>
              <th className="p-3">Review</th>
              <th className="p-3">Error</th>
              <th className="p-3">Publish rate</th>
              <th className="p-3">Last success</th>
            </tr>
          </thead>
          <tbody>
            {health.connectors.length === 0 && <tr><td colSpan={8} className="p-4 text-slate-500">No connectors.</td></tr>}
            {health.connectors.map((c) => (
              <tr key={c.connector_id} className="border-t">
                <td className="p-3">
                  <p className="font-medium">{c.display_name ?? c.type}</p>
                  <p className="text-xs text-slate-500">{c.type}</p>
                </td>
                <td className="p-3 capitalize">
                  {c.status}
                  {c.consecutive_failures > 0 && <span className="ml-1 text-xs text-red-600">({c.consecutive_failures}×)</span>}
                </td>
                <td className="p-3">{c.records}</td>
                <td className="p-3">{c.published}</td>
                <td className="p-3">{c.review}</td>
                <td className={`p-3 ${c.error ? "text-red-700" : ""}`}>{c.error}</td>
                <td className="p-3">{c.publish_rate == null ? "—" : `${Math.round(c.publish_rate * 100)}%`}</td>
                <td className="p-3 text-xs text-slate-600">{relativeTime(c.last_success_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function pct(v: number): string {
  return `${Math.round(v * 1000) / 10}%`;
}

function TurnStatsCard({ title, stats }: { title: string; stats: TurnStats }) {
  const cells: [string, string][] = [
    ["Turns", String(stats.turns)],
    ["p50", stats.latency_ms.p50 == null ? "—" : `${stats.latency_ms.p50} ms`],
    ["p95", stats.latency_ms.p95 == null ? "—" : `${stats.latency_ms.p95} ms`],
    ["Fallback rate", pct(stats.fallback_rate)],
    ["Guard failures", String(stats.guard_failures)],
    ["Tool failures", String(stats.tool_failures)],
    ["LLM fallbacks", String(stats.llm_fallbacks)],
  ];
  return (
    <div className="rounded-2xl border bg-white p-4">
      <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
      <dl className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        {cells.map(([k, v]) => (
          <div key={k}>
            <dt className="text-[10px] uppercase tracking-wide text-slate-500">{k}</dt>
            <dd className="text-lg font-semibold">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function OpsTab({ say }: { say: Say }) {
  const [ops, setOps] = useState<OpsOverview | null>(null);

  useEffect(() => {
    const load = () => adminApi.ops().then((r) => (r.data ? setOps(r.data) : say(r, "")));
    void load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [say]);

  if (!ops) return <p role="status" className="text-sm text-slate-500">Loading…</p>;

  return (
    <div className="grid gap-6">
      <section aria-label="Active alerts">
        {ops.alerts.length === 0 ? (
          <p className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">
            No active alerts. {ops.llm_configured ? "" : "No LLM provider configured — template replies are expected, so the fallback-rate alert is disabled."}
          </p>
        ) : (
          <ul className="grid gap-2">
            {ops.alerts.map((a) => (
              <li
                key={a.code}
                role="alert"
                className={`rounded-xl border p-3 text-sm ${a.severity === "critical" ? "border-red-300 bg-red-50 text-red-800" : "border-amber-300 bg-amber-50 text-amber-800"}`}
              >
                <span className="font-semibold uppercase">{a.severity}</span> · {a.message}
              </li>
            ))}
          </ul>
        )}
      </section>

      <TurnStatsCard title={`Last ${ops.window_minutes} minutes`} stats={ops.window} />
      <TurnStatsCard title="Last 1,000 turns" stats={ops.recent_1000} />

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-700">Consumers</h3>
          <table className="mt-2 w-full text-left text-sm">
            <thead className="text-xs text-slate-500"><tr><th className="py-1">Consumer</th><th className="py-1">Pending</th><th className="py-1">Lag</th></tr></thead>
            <tbody>
              {Object.entries(ops.consumers).map(([name, c]) => (
                <tr key={name} className={`border-t ${c.lag_s > ops.thresholds.consumer_lag_s ? "text-red-700" : ""}`}>
                  <td className="py-2">{name}</td>
                  <td className="py-2">{c.pending}</td>
                  <td className="py-2">{c.lag_s}s</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-sm text-slate-600">
            Review queue: <span className={ops.review_open > ops.thresholds.review_queue ? "font-semibold text-red-700" : "font-semibold"}>{ops.review_open}</span> open
          </p>
        </div>
        <div className="rounded-2xl border bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-700">Connectors</h3>
          {ops.connectors.length === 0 && <p className="mt-2 text-sm text-slate-500">No connectors.</p>}
          <ul className="mt-2 grid gap-2 text-sm">
            {ops.connectors.map((c) => (
              <li key={c.connector_id} className="flex items-center justify-between border-t pt-2">
                <span>
                  <span className="font-medium">{c.display_name ?? c.type}</span>
                  <span className="ml-2 text-xs capitalize text-slate-500">{c.status}</span>
                </span>
                <span className={c.consecutive_failures >= ops.thresholds.connector_failures ? "text-red-700" : "text-slate-600"}>
                  {c.consecutive_failures} failures · {relativeTime(c.last_success_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <p className="text-xs text-slate-500">
        Thresholds: fallback &gt; {pct(ops.thresholds.fallback_rate)} / {ops.window_minutes} min · consumer lag &gt; {ops.thresholds.consumer_lag_s}s ·
        connector ≥ {ops.thresholds.connector_failures} consecutive failures · review queue &gt; {ops.thresholds.review_queue}. Generated {relativeTime(ops.generated_at)}.
      </p>
    </div>
  );
}
