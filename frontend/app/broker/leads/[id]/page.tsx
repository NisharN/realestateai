"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { brokerApi, type BrokerLeadDetail, type LeadPatch, type TimelineItem, type ViewingStatus } from "@/lib/api";
import { bandTone, formatBudget, relativeTime, STAGE_LABELS } from "@/lib/broker-format";
import { useBrokerScope } from "@/lib/use-broker-scope";
import { StatusBanner } from "@/components/broker/lead-card";

const STAGES = Object.keys(STAGE_LABELS);
const VIEWING_NEXT: Record<ViewingStatus, ViewingStatus[]> = {
  requested: ["confirmed", "cancelled"],
  confirmed: ["done", "no_show", "cancelled"],
  done: [],
  no_show: ["confirmed"],
  cancelled: ["requested"],
};
const VIEWING_LABELS: Record<ViewingStatus, string> = {
  requested: "Requested",
  confirmed: "Confirmed",
  done: "Done",
  no_show: "No-show",
  cancelled: "Cancelled",
};

function formatWhen(iso: string | null): string {
  if (!iso) return "time TBC";
  return new Date(iso).toLocaleString("en-AE", { timeZone: "Asia/Dubai", dateStyle: "medium", timeStyle: "short" });
}

function describe(item: TimelineItem): string {
  if (item.kind === "message") return `${item.role === "user" ? "Buyer" : "Assistant"}${item.channel ? ` (${item.channel})` : ""}: ${item.text}`;
  if (item.kind === "change") return `${item.by ?? "system"} changed ${item.field}: ${JSON.stringify(item.old)} → ${JSON.stringify(item.new)}`;
  return item.type;
}

export default function LeadDetailPage() {
  const { id } = useParams<{ id: string }>();
  const scope = useBrokerScope();
  const [data, setData] = useState<BrokerLeadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [viewingForm, setViewingForm] = useState({ starts_at: "", property_id: "", notes: "" });
  const [bookingViewing, setBookingViewing] = useState(false);

  const load = useCallback(async () => {
    const r = await brokerApi.lead(id);
    if (r.error) return setError(r.error);
    setError(null);
    setData(r.data ?? null);
    const lead = r.data?.lead;
    if (lead) {
      setForm({
        purpose: lead.purpose ?? "",
        budget_min_aed: lead.budget_min_aed?.toString() ?? "",
        budget_max_aed: lead.budget_max_aed?.toString() ?? "",
        budget_period: lead.budget_period ?? "",
        community_ids: (lead.community_ids ?? lead.areas ?? []).join(", "),
        property_types: (lead.property_types ?? (lead.property_type ? [lead.property_type] : [])).join(", "),
        timeline: lead.timeline ?? "",
        payment: lead.payment ?? "",
        stage: lead.stage,
        notes: lead.notes ?? "",
      });
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!data) return;
    setSaving(true);
    setNotice(null);
    const list = (v: string) => v.split(",").map((s) => s.trim()).filter(Boolean);
    const num = (v: string) => (v.trim() === "" ? undefined : Number(v));
    const patch: LeadPatch = {};
    const lead = data.lead;
    if (form.purpose !== (lead.purpose ?? "")) patch.purpose = form.purpose;
    if (num(form.budget_min_aed) !== (lead.budget_min_aed ?? undefined)) patch.budget_min_aed = num(form.budget_min_aed);
    if (num(form.budget_max_aed) !== (lead.budget_max_aed ?? undefined)) patch.budget_max_aed = num(form.budget_max_aed);
    if (form.budget_period !== (lead.budget_period ?? "")) patch.budget_period = form.budget_period;
    if (form.community_ids !== (lead.community_ids ?? lead.areas ?? []).join(", ")) patch.community_ids = list(form.community_ids);
    if (form.property_types !== (lead.property_types ?? (lead.property_type ? [lead.property_type] : [])).join(", ")) patch.property_types = list(form.property_types);
    if (form.timeline !== (lead.timeline ?? "")) patch.timeline = form.timeline;
    if (form.payment !== (lead.payment ?? "")) patch.payment = form.payment;
    if (form.stage !== lead.stage) patch.stage = form.stage;
    if (form.notes !== (lead.notes ?? "")) patch.notes = form.notes;
    const clean = Object.fromEntries(Object.entries(patch).filter(([, v]) => v !== undefined)) as LeadPatch;
    if (Object.keys(clean).length === 0) {
      setNotice("No changes to save.");
      setSaving(false);
      return;
    }
    const r = await brokerApi.patchLead(id, clean);
    if (r.error) setNotice(r.error);
    else {
      setNotice(`Saved: ${r.data?.changed.join(", ") || "no fields"}`);
      void load();
    }
    setSaving(false);
  };

  const act = async (kind: "accept" | "decline") => {
    if (!data?.handoff) return;
    const r =
      kind === "accept"
        ? await brokerApi.accept(data.handoff.id, scope.brokerId)
        : await brokerApi.decline(data.handoff.id, { broker_id: scope.brokerId, reason: "declined_from_detail" });
    setNotice(r.error ?? (kind === "accept" ? "Handoff accepted." : "Handoff declined."));
    if (!r.error) void load();
  };

  const bookViewing = async (e: FormEvent) => {
    e.preventDefault();
    if (!data || !viewingForm.starts_at) return;
    setBookingViewing(true);
    const r = await brokerApi.createViewing({
      lead_id: data.lead.id,
      starts_at: new Date(viewingForm.starts_at).toISOString(),
      property_id: viewingForm.property_id.trim() || null,
      notes: viewingForm.notes.trim() || undefined,
      broker_id: scope.brokerId,
      confirmed: true,
    });
    setBookingViewing(false);
    setNotice(r.error ?? "Viewing booked.");
    if (!r.error) {
      setViewingForm({ starts_at: "", property_id: "", notes: "" });
      void load();
    }
  };

  const setViewingStatus = async (id: string, status: ViewingStatus) => {
    const r = await brokerApi.patchViewing(id, { status });
    setNotice(r.error ?? `Viewing ${VIEWING_LABELS[status].toLowerCase()}.`);
    if (!r.error) void load();
  };

  const field = (name: string, label: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label className="grid gap-1 text-xs font-medium text-slate-600">
      {label}
      <input
        aria-label={label}
        value={form[name] ?? ""}
        onChange={(e) => setForm({ ...form, [name]: e.target.value })}
        className="rounded-lg border px-3 py-2 text-sm font-normal text-slate-900"
        {...props}
      />
    </label>
  );

  const lead = data?.lead;
  const brief = data?.brief;

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-8">
      <div className="mx-auto max-w-6xl">
        <Link href="/broker" className="text-sm text-slate-500 hover:underline">
          ← Broker Today
        </Link>
        <StatusBanner error={error} loading={!data && !error} />

        {lead && (
          <>
            <header className="mt-3 flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 className="text-3xl font-semibold">{lead.name}</h1>
                <p className="mt-1 text-slate-600">
                  {lead.phone ?? "no phone"} {lead.email ? `· ${lead.email}` : ""} · {lead.language.toUpperCase()} · source {lead.source ?? "unknown"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className={`rounded-full px-3 py-1 text-sm font-medium ${bandTone(lead.band)}`}>
                  {lead.band ?? "unscored"} · {lead.score}
                </span>
                <span className="rounded-full bg-white px-3 py-1 text-sm ring-1 ring-slate-200">{STAGE_LABELS[lead.stage] ?? lead.stage}</span>
              </div>
            </header>

            {notice && <p role="status" className="mt-4 rounded-xl bg-blue-50 p-3 text-sm text-blue-800">{notice}</p>}

            <div className="mt-6 grid gap-6 lg:grid-cols-[1.2fr_1fr]">
              <div className="grid gap-6">
                <section className="rounded-2xl border bg-white p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Brief</h2>
                  {brief ? (
                    <div className="mt-3 grid gap-2 text-sm">
                      <p className="text-base font-medium">{brief.headline}</p>
                      <p className="text-slate-700">Next step: {brief.next_step}</p>
                      {Array.isArray(brief.score_reasons) && brief.score_reasons.length > 0 && (
                        <ul className="list-disc pl-5 text-slate-600">
                          {brief.score_reasons.map((r) => <li key={r}>{r}</li>)}
                        </ul>
                      )}
                      {Array.isArray(brief.objections) && brief.objections.length > 0 && (
                        <p className="text-slate-600">Objections: {brief.objections.join("; ")}</p>
                      )}
                    </div>
                  ) : (
                    <p className="mt-3 text-sm text-slate-500">No handoff brief yet — this lead has not been handed off.</p>
                  )}
                  {Array.isArray(lead.score_reasons) && lead.score_reasons.length > 0 && !brief && (
                    <ul className="mt-3 list-disc pl-5 text-sm text-slate-600">
                      {lead.score_reasons.map((r) => <li key={r}>{r}</li>)}
                    </ul>
                  )}
                </section>

                {data.handoff && (
                  <section className="rounded-2xl border bg-white p-5">
                    <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Handoff</h2>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
                      <span className="capitalize">{data.handoff.status}</span>
                      <span className="text-slate-500">to {data.handoff.broker_name ?? data.handoff.broker_id ?? "unassigned"}</span>
                      {data.handoff.slot_text && <span className="text-slate-500">wants {data.handoff.slot_text}</span>}
                      <span className="text-slate-400">{relativeTime(data.handoff.created_at)}</span>
                      {data.handoff.status === "pending" && (
                        <span className="ml-auto flex gap-2">
                          <button onClick={() => act("accept")} className="rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white">
                            Accept
                          </button>
                          <button onClick={() => act("decline")} className="rounded-lg border px-3 py-1.5 text-xs font-semibold">
                            Decline
                          </button>
                        </span>
                      )}
                    </div>
                    {Array.isArray(data.handoff.routing_reasons) && data.handoff.routing_reasons.length > 0 && (
                      <p className="mt-2 text-xs text-slate-500">Routed by: {data.handoff.routing_reasons.join(", ")}</p>
                    )}
                  </section>
                )}

                <section className="rounded-2xl border bg-white p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Timeline</h2>
                  {data.timeline.length === 0 ? (
                    <p className="mt-3 text-sm text-slate-500">No activity recorded.</p>
                  ) : (
                    <ol className="mt-3 grid gap-2 text-sm">
                      {data.timeline.map((item, i) => (
                        <li key={i} className="flex gap-3">
                          <span className="w-16 shrink-0 text-xs text-slate-400">{relativeTime(item.at)}</span>
                          <span className={item.kind === "message" ? "text-slate-800" : "text-slate-600"}>{describe(item)}</span>
                        </li>
                      ))}
                    </ol>
                  )}
                </section>
              </div>

              <div className="grid gap-6">
                <form onSubmit={save} className="rounded-2xl border bg-white p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Edit requirements</h2>
                  <p className="mt-1 text-xs text-slate-500">Current: {formatBudget(lead)}. Edits are logged and mark fields as broker-confirmed.</p>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <label className="grid gap-1 text-xs font-medium text-slate-600">
                      Purpose
                      <select aria-label="Purpose" value={form.purpose ?? ""} onChange={(e) => setForm({ ...form, purpose: e.target.value })} className="rounded-lg border px-3 py-2 text-sm font-normal">
                        <option value="">—</option>
                        <option value="buy">Buy</option>
                        <option value="rent">Rent</option>
                        <option value="invest">Invest</option>
                      </select>
                    </label>
                    <label className="grid gap-1 text-xs font-medium text-slate-600">
                      Stage
                      <select aria-label="Stage" value={form.stage ?? ""} onChange={(e) => setForm({ ...form, stage: e.target.value })} className="rounded-lg border px-3 py-2 text-sm font-normal">
                        {STAGES.map((s) => <option key={s} value={s}>{STAGE_LABELS[s]}</option>)}
                      </select>
                    </label>
                    {field("budget_min_aed", "Budget min (AED)", { type: "number", min: 0 })}
                    {field("budget_max_aed", "Budget max (AED)", { type: "number", min: 0 })}
                    <label className="grid gap-1 text-xs font-medium text-slate-600">
                      Budget period
                      <select aria-label="Budget period" value={form.budget_period ?? ""} onChange={(e) => setForm({ ...form, budget_period: e.target.value })} className="rounded-lg border px-3 py-2 text-sm font-normal">
                        <option value="">—</option>
                        <option value="total">Total</option>
                        <option value="year">Per year</option>
                        <option value="month">Per month</option>
                      </select>
                    </label>
                    {field("timeline", "Timeline", { placeholder: "e.g. 1-3 months" })}
                    {field("community_ids", "Communities (comma-separated)")}
                    {field("property_types", "Property types (comma-separated)")}
                    {field("payment", "Payment", { placeholder: "cash / mortgage" })}
                  </div>
                  <label className="mt-3 grid gap-1 text-xs font-medium text-slate-600">
                    Notes
                    <textarea aria-label="Notes" value={form.notes ?? ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={3} className="rounded-lg border px-3 py-2 text-sm font-normal" />
                  </label>
                  <button disabled={saving} className="mt-4 rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50">
                    {saving ? "Saving…" : "Save changes"}
                  </button>
                </form>

                <section className="rounded-2xl border bg-white p-5 text-sm">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">Sources & follow-ups</h2>
                  {data.sources.length === 0 ? (
                    <p className="mt-3 text-slate-500">No ingestion sources — created from conversation.</p>
                  ) : (
                    <ul className="mt-3 grid gap-1 text-slate-700">
                      {data.sources.map((s, i) => (
                        <li key={i}>
                          {String(s.source ?? "unknown")} {s.first_seen_at ? `· first seen ${relativeTime(String(s.first_seen_at))}` : ""}
                        </li>
                      ))}
                    </ul>
                  )}
                  <h3 className="mt-4 text-xs font-semibold uppercase text-slate-500">Viewings</h3>
                  {data.viewings.length === 0 ? (
                    <p className="mt-1 text-slate-500">No viewings yet.</p>
                  ) : (
                    <ul className="mt-1 grid gap-2 text-slate-700">
                      {data.viewings.map((v) => (
                        <li key={v.id} className="flex flex-wrap items-center gap-2">
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium">{VIEWING_LABELS[v.status]}</span>
                          <span>{formatWhen(v.starts_at)}</span>
                          {v.property_id && <span className="text-xs text-slate-500">property {v.property_id}</span>}
                          <span className="text-xs text-slate-400">via {v.source}</span>
                          {VIEWING_NEXT[v.status].map((next) => (
                            <button
                              key={next}
                              type="button"
                              onClick={() => void setViewingStatus(v.id, next)}
                              className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
                            >
                              {VIEWING_LABELS[next]}
                            </button>
                          ))}
                        </li>
                      ))}
                    </ul>
                  )}
                  <form onSubmit={bookViewing} className="mt-2 grid gap-2 rounded-lg border border-slate-200 p-3">
                    <p className="text-xs font-medium text-slate-600">Book a viewing</p>
                    <input
                      type="datetime-local"
                      required
                      value={viewingForm.starts_at}
                      onChange={(e) => setViewingForm({ ...viewingForm, starts_at: e.target.value })}
                      className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                      aria-label="Viewing date and time"
                    />
                    <input
                      placeholder="Property id (optional)"
                      value={viewingForm.property_id}
                      onChange={(e) => setViewingForm({ ...viewingForm, property_id: e.target.value })}
                      className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                    />
                    <input
                      placeholder="Notes (optional)"
                      value={viewingForm.notes}
                      onChange={(e) => setViewingForm({ ...viewingForm, notes: e.target.value })}
                      className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                    />
                    <button
                      type="submit"
                      disabled={bookingViewing || !viewingForm.starts_at}
                      className="justify-self-start rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
                    >
                      {bookingViewing ? "Booking…" : "Book viewing"}
                    </button>
                  </form>
                  <h3 className="mt-4 text-xs font-semibold uppercase text-slate-500">Follow-ups</h3>
                  {data.followups.length === 0 ? (
                    <p className="mt-1 text-slate-500">None scheduled.</p>
                  ) : (
                    <ul className="mt-1 grid gap-1 text-slate-700">
                      {data.followups.map((f) => (
                        <li key={f.id}>
                          Touch {f.touch} · {f.template_key} · {f.status} · {relativeTime(f.due_at)}
                        </li>
                      ))}
                    </ul>
                  )}
                  {lead.consent && (
                    <p className="mt-4 text-xs text-slate-500">
                      Consent: marketing {String(lead.consent.marketing ?? "unknown")}
                    </p>
                  )}
                </section>
              </div>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
