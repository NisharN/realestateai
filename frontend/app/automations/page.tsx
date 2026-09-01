"use client";

/**
 * Automations — the fixed workflow templates, what they're about to do, and
 * what they've sent.
 *
 * Deliberately not a drag-and-drop canvas. A broker, a technical consultant,
 * and a PM all independently rejected the builder: it rebuilds n8n by hand,
 * it contradicts a forward-deployed model where the customer pays precisely so
 * they don't configure anything, and — in the broker's words — no agent is
 * opening a node editor between viewings. So this page shows the presets, a
 * live preview of pending actions, and the message log.
 */

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  Clock,
  Copy,
  MessageSquare,
  Play,
  RefreshCw,
  Zap,
} from "lucide-react";
import {
  workflowsApi,
  type OutboxMessage,
  type RefreshSuggestion,
  type WorkflowAction,
} from "@/lib/api";

type Tab = "pending" | "outbox" | "listings";

interface TemplatesPayload {
  builder_enabled: boolean;
  note: string;
  templates: { id: string; label: string; enabled: boolean }[];
  settings: Record<string, number>;
  voice_gate: {
    outbound_enabled: boolean;
    requires_human_approval: boolean;
    note: string;
  };
}

export default function AutomationsPage() {
  const [tab, setTab] = useState<Tab>("pending");
  const [templates, setTemplates] = useState<TemplatesPayload | null>(null);
  const [actions, setActions] = useState<WorkflowAction[]>([]);
  const [byTemplate, setByTemplate] = useState<Record<string, number>>({});
  const [outbox, setOutbox] = useState<OutboxMessage[]>([]);
  const [outboxMode, setOutboxMode] = useState<{ mode: string; delivered: boolean } | null>(null);
  const [suggestions, setSuggestions] = useState<RefreshSuggestion[]>([]);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const [t, p, o, l] = await Promise.all([
      workflowsApi.templates(),
      workflowsApi.preview(),
      workflowsApi.outbox(),
      workflowsApi.listingRefresh(),
    ]);
    if (t.data) setTemplates(t.data);
    if (p.data) {
      setActions(p.data.actions);
      setByTemplate(p.data.by_template);
    }
    if (o.data) {
      setOutbox(o.data.messages);
      setOutboxMode({ mode: o.data.mode, delivered: o.data.delivered });
    }
    if (l.data) setSuggestions(l.data.suggestions);
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function runNow() {
    setRunning(true);
    await workflowsApi.run();
    await refresh();
    setRunning(false);
  }

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-gray-50 p-6">
      <div className="max-w-6xl mx-auto">
        <header className="flex items-start justify-between gap-4 mb-6 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Automations</h1>
            <p className="text-sm text-gray-500 mt-1">
              Preset workflows configured for this brokerage.
            </p>
          </div>
          <button
            onClick={runNow}
            disabled={running || loading}
            className="flex items-center gap-2 px-4 py-2.5 bg-gray-900 text-white rounded-xl text-sm font-medium hover:bg-gray-800 transition disabled:opacity-40"
          >
            {running ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {running ? "Running…" : "Run now"}
          </button>
        </header>

        {outboxMode && !outboxMode.delivered && (
          <div className="mb-4 flex items-start gap-2 px-4 py-3 rounded-xl bg-amber-50 border border-amber-200">
            <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-amber-800">
              <span className="font-medium">Simulation mode.</span> Messages are recorded
              below but not delivered. Set{" "}
              <code className="px-1 py-0.5 bg-amber-100 rounded text-xs">DATA_MODE_WHATSAPP=live</code>{" "}
              once Meta Business Verification completes.
            </p>
          </div>
        )}

        <TemplateGrid templates={templates} counts={byTemplate} />

        {templates && !templates.voice_gate.outbound_enabled && (
          <div className="mt-4 flex items-start gap-2 px-4 py-3 rounded-xl bg-gray-100 border border-gray-200">
            <Clock className="w-4 h-4 text-gray-500 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-gray-600">
              Outbound voice is disabled. {templates.voice_gate.note}
            </p>
          </div>
        )}

        <div className="mt-8 flex gap-1 border-b border-gray-200">
          {(
            [
              ["pending", `Pending (${actions.length})`],
              ["outbox", `Message log (${outbox.length})`],
              ["listings", `Listing refresh (${suggestions.length})`],
            ] as [Tab, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition ${
                tab === id
                  ? "border-gray-900 text-gray-900"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="mt-6">
          {loading && <p className="text-sm text-gray-500">Loading…</p>}
          {!loading && tab === "pending" && <PendingList actions={actions} />}
          {!loading && tab === "outbox" && <OutboxList messages={outbox} />}
          {!loading && tab === "listings" && <RefreshList suggestions={suggestions} />}
        </div>
      </div>
    </div>
  );
}

function TemplateGrid({
  templates,
  counts,
}: {
  templates: TemplatesPayload | null;
  counts: Record<string, number>;
}) {
  if (!templates) return null;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {templates.templates.map((t) => (
        <div
          key={t.id}
          className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 flex items-start gap-3"
        >
          <div className={`p-2 rounded-xl ${t.enabled ? "bg-green-50" : "bg-gray-100"}`}>
            <Zap className={`w-4 h-4 ${t.enabled ? "text-green-600" : "text-gray-400"}`} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-gray-900 leading-snug">{t.label}</p>
            <p className="text-xs text-gray-500 mt-1">
              {counts[t.id] ?? 0} pending
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

const ACTION_LABELS: Record<string, string> = {
  send_whatsapp: "WhatsApp",
  notify_agent: "Notify agent",
  escalate_to_human: "Escalate",
  generate_listing_copy: "Refresh copy",
  request_voice_approval: "Voice approval",
};

function PendingList({ actions }: { actions: WorkflowAction[] }) {
  if (actions.length === 0) {
    return <EmptyState label="Nothing pending — everything is up to date." />;
  }
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm divide-y divide-gray-50">
      {actions.map((a, i) => (
        <motion.div
          key={`${a.template}-${a.subject_id}-${i}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: Math.min(i * 0.01, 0.2) }}
          className="p-4 flex items-start gap-3"
        >
          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 text-gray-600 flex-shrink-0">
            {ACTION_LABELS[a.action] ?? a.action}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm text-gray-900 truncate">
              {a.message ?? `${a.subject_type} ${a.subject_id}`}
            </p>
            <p className="text-xs text-gray-500 mt-0.5">{a.reason}</p>
          </div>
          {a.recipient && (
            <span className="text-xs text-gray-400 flex-shrink-0">{a.recipient}</span>
          )}
        </motion.div>
      ))}
    </div>
  );
}

function OutboxList({ messages }: { messages: OutboxMessage[] }) {
  if (messages.length === 0) {
    return <EmptyState label="No messages yet. Use “Run now” to evaluate the templates." />;
  }
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm divide-y divide-gray-50">
      {messages.map((m) => (
        <div key={m.id} className="p-4 flex items-start gap-3">
          <MessageSquare className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-medium text-gray-900">{m.to}</span>
              <StatusPill status={m.status} />
            </div>
            <p className="text-sm text-gray-600">{m.body}</p>
            {m.error && <p className="text-xs text-red-600 mt-1">{m.error}</p>}
          </div>
          <span className="text-xs text-gray-400 flex-shrink-0">
            {new Date(m.created_at).toLocaleTimeString()}
          </span>
        </div>
      ))}
    </div>
  );
}

function StatusPill({ status }: { status: OutboxMessage["status"] }) {
  const styles: Record<string, string> = {
    sent: "bg-green-100 text-green-700",
    simulated: "bg-amber-100 text-amber-700",
    queued: "bg-gray-100 text-gray-600",
    failed: "bg-red-100 text-red-700",
  };
  return (
    <span className={`px-2 py-0.5 text-xs rounded-full ${styles[status] ?? styles.queued}`}>
      {status}
    </span>
  );
}

function RefreshList({ suggestions }: { suggestions: RefreshSuggestion[] }) {
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(s: RefreshSuggestion) {
    await navigator.clipboard.writeText(s.description);
    setCopied(s.property_id);
    setTimeout(() => setCopied(null), 1800);
  }

  if (suggestions.length === 0) {
    return <EmptyState label="No stale listings right now." />;
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Copy and repost these yourself — this product never posts to Bayut,
        Property Finder, or Dubizzle on your behalf.
      </p>
      {suggestions.map((s) => (
        <div key={s.property_id} className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
          <div className="flex items-start justify-between gap-3 mb-2">
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-900 truncate">{s.title}</p>
              <p className="text-xs text-gray-500">
                {s.area} · stale {s.days_stale} days
              </p>
            </div>
            <button
              onClick={() => copy(s)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded-lg text-xs font-medium text-gray-700 transition flex-shrink-0"
            >
              {copied === s.property_id ? (
                <>
                  <Check className="w-3 h-3" /> Copied
                </>
              ) : (
                <>
                  <Copy className="w-3 h-3" /> Copy
                </>
              )}
            </button>
          </div>
          <p className="text-sm text-gray-700 leading-relaxed">{s.description}</p>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-12 text-center">
      <p className="text-sm text-gray-500">{label}</p>
    </div>
  );
}
