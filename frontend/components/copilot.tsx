"use client";

/**
 * Copilot — a plain-language question box over the typed analytics API.
 * "Top 5 leads to call today", "who wants Palm Jumeirah", "hot leads that went
 * quiet". Answers come back as a short summary, the matching leads and the
 * next actions a broker would actually take (open, schedule follow-ups, auto-close).
 */

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { ArrowUpRight, CalendarPlus, Loader2, MessageSquareText, Mic, Sparkles, XCircle } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ui/page";
import { analyticsApi, coworkApi, isLeadRow, type AnalyticsAction, type AnalyticsLeadRow, type AnalyticsResult } from "@/lib/api";

const BAND_TONE: Record<AnalyticsLeadRow["band"], BadgeTone> = { hot: "danger", warm: "warning", cold: "neutral" };

const FALLBACK_QUESTIONS = ["Top 5 leads to call today", "Who wants Palm Jumeirah?", "Hot leads that went quiet for 3 days", "New leads this week"];

interface Turn {
  question: string;
  result?: AnalyticsResult;
  error?: string;
}

export function Copilot({ compact = false, initialQuestion }: { compact?: boolean; initialQuestion?: string }) {
  const [questions, setQuestions] = useState<string[]>(FALLBACK_QUESTIONS);
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; ok: boolean } | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void analyticsApi.questions().then((r) => {
      if (r.data?.questions?.length) setQuestions(r.data.questions);
    });
  }, []);

  const ask = useCallback(async (q: string) => {
    const question = q.trim();
    if (!question) return;
    setBusy(true);
    setText("");
    setNotice(null);
    const r = await analyticsApi.ask(question, 5);
    setTurns((prev) => [...prev, r.data ? { question, result: r.data } : { question, error: r.error ?? "Couldn't answer that" }]);
    setBusy(false);
    requestAnimationFrame(() => bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  }, []);

  useEffect(() => {
    if (initialQuestion) void ask(initialQuestion);
  }, [initialQuestion, ask]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(text);
  };

  const runAction = async (action: AnalyticsAction, question: string) => {
    if (!action.lead_ids?.length) return;
    setBusy(true);
    const stepParams: Record<string, unknown> = action.type === "leads.reject" ? { max_score: 100, stale_hours: 0, reason: "closed from Copilot" } : {};
    const r = await coworkApi.createRoutine({
      name: `${action.label} · ${question}`.slice(0, 120),
      description: "Created from Copilot",
      schedule: { kind: "daily", at: "09:00" },
      enabled: false,
      steps: [
        { type: "leads.select", params: { lead_ids: action.lead_ids, limit: action.lead_ids.length } },
        { type: action.type, params: stepParams },
      ],
    });
    if (r.data) {
      const run = await coworkApi.runRoutine(r.data.id);
      setNotice(run.data ? { text: `${action.label}: done for ${run.data.summary.leads ?? action.lead_ids.length} leads.`, ok: true } : { text: run.error ?? "Run failed", ok: false });
    } else {
      setNotice({ text: r.error ?? "Couldn't run that action", ok: false });
    }
    setBusy(false);
  };

  return (
    <section className={`ui-card flex flex-col ${compact ? "" : "min-h-[22rem]"}`} aria-label="Copilot">
      <header className="flex items-center gap-2 border-b border-border px-4 py-3">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand/10 text-brand">
          <Sparkles className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">Copilot</p>
          <p className="truncate text-xs text-muted-foreground">Ask about your leads in plain language</p>
        </div>
      </header>

      <div className={`flex-1 space-y-4 overflow-y-auto px-4 py-4 ${compact ? "max-h-[26rem]" : ""}`}>
        {turns.length === 0 && (
          <div className="flex flex-wrap gap-2">
            {questions.slice(0, compact ? 4 : 8).map((q) => (
              <button key={q} type="button" onClick={() => void ask(q)} className="ui-btn-secondary ui-btn-sm rounded-full" disabled={busy}>
                {q}
              </button>
            ))}
          </div>
        )}
        {turns.map((t, i) => (
          <div key={`${t.question}-${i}`} className="space-y-2">
            <p className="ms-auto max-w-[85%] rounded-2xl rounded-br-md bg-muted px-3 py-2 text-sm text-foreground">{t.question}</p>
            {t.error && (
              <p role="alert" className="flex items-center gap-2 rounded-xl bg-danger-soft px-3 py-2 text-sm text-danger">
                <XCircle className="h-4 w-4" /> {t.error}
              </p>
            )}
            {t.result && <Answer result={t.result} onAction={(a) => void runAction(a, t.question)} busy={busy} />}
          </div>
        ))}
        {busy && (
          <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Thinking…
          </p>
        )}
        {notice && (
          <p role={notice.ok ? "status" : "alert"} className={`rounded-xl px-3 py-2 text-xs ${notice.ok ? "bg-success-soft text-success" : "bg-danger-soft text-danger"}`}>
            {notice.text}
          </p>
        )}
        <div ref={bottom} />
      </div>

      <form onSubmit={submit} className="flex items-center gap-2 border-t border-border p-3">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Who should I call today?"
          aria-label="Ask Copilot"
          className="ui-input flex-1"
          disabled={busy}
        />
        <button type="submit" className="ui-btn-primary ui-btn-sm" disabled={busy || !text.trim()}>
          Ask
        </button>
      </form>
    </section>
  );
}

function Answer({ result, onAction, busy }: { result: AnalyticsResult; onAction: (a: AnalyticsAction) => void; busy: boolean }) {
  const leads = result.rows.filter(isLeadRow);
  const other = result.rows.filter((r) => !isLeadRow(r)) as Record<string, string | number | null>[];
  return (
    <div className="space-y-3 rounded-2xl rounded-bl-md border border-border bg-card p-3">
      <p className="text-sm text-foreground">{result.summary}</p>

      {leads.length > 0 && (
        <ul className="divide-y divide-border">
          {leads.map((l) => (
            <li key={l.id} className="flex flex-col gap-2 py-2 sm:flex-row sm:items-center sm:gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link href={`/broker/leads/${l.id}`} className="truncate text-sm font-medium text-foreground hover:underline">
                    {l.name}
                  </Link>
                  <Badge tone={BAND_TONE[l.band]}>{l.band}</Badge>
                  <span className="text-xs tabular-nums text-muted-foreground">{l.score}</span>
                </div>
                <p className="text-xs text-muted-foreground sm:truncate">
                  {[l.areas?.join(", "), l.purpose, l.budget_max_aed ? `AED ${compact(l.budget_max_aed)}` : null, l.silent_hours != null ? `${l.silent_hours >= 48 ? `${Math.round(l.silent_hours / 24)}d` : `${l.silent_hours}h`} quiet` : null]
                    .filter(Boolean)
                    .join(" · ") || l.stage}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1 sm:justify-end">
                {l.phone && (
                  <a href={`https://wa.me/${l.phone.replace(/\D/g, "")}`} target="_blank" rel="noreferrer" className="ui-btn-ghost ui-btn-sm" aria-label={`WhatsApp ${l.name}`} title="WhatsApp">
                    <MessageSquareText className="h-3.5 w-3.5" />
                  </a>
                )}
                <Link href={`/cowork/routines?template=voice_note_followup`} className="ui-btn-ghost ui-btn-sm" aria-label={`Voice note routine for ${l.name}`} title="Voice note">
                  <Mic className="h-3.5 w-3.5" />
                </Link>
                <Link href={`/broker/leads/${l.id}#viewing`} className="ui-btn-ghost ui-btn-sm" aria-label={`Book viewing for ${l.name}`} title="Book viewing">
                  <CalendarPlus className="h-3.5 w-3.5" />
                </Link>
                <Link href={`/broker/leads/${l.id}`} className="ui-btn-ghost ui-btn-sm" aria-label={`Open ${l.name}`} title="Open lead">
                  <ArrowUpRight className="h-3.5 w-3.5" />
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}

      {other.length > 0 && (
        <table className="ui-table w-full text-sm">
          <thead>
            <tr>
              {Object.keys(other[0]).map((k) => (
                <th key={k} className="text-start">{k.replace(/_/g, " ")}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {other.map((row, i) => (
              <tr key={i}>
                {Object.values(row).map((v, j) => (
                  <td key={j} className="tabular-nums">{typeof v === "number" && !Number.isInteger(v) ? v.toFixed(2) : String(v ?? "—")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {result.suggested_actions.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-1">
          {result.suggested_actions
            .filter((a) => a.lead_ids?.length)
            .map((a) => (
              <button key={a.type + a.label} type="button" className="ui-btn-secondary ui-btn-sm" onClick={() => onAction(a)} disabled={busy}>
                {a.label}
              </button>
            ))}
          <Link href={`/cowork/routines?new=1`} className="ui-btn-ghost ui-btn-sm">
            Make this a routine
          </Link>
        </div>
      )}
    </div>
  );
}

function compact(v: number): string {
  return v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1).replace(/\.0$/, "")}M` : `${Math.round(v / 1000)}K`;
}
