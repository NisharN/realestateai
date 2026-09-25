"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { brokerApi, type BrokerToday } from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";
import { useBrokerScope } from "@/lib/use-broker-scope";
import { LeadCard, Panel, StatusBanner } from "@/components/broker/lead-card";

export default function BrokerTodayPage() {
  const scope = useBrokerScope();
  const [data, setData] = useState<BrokerToday | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await brokerApi.today(scope.brokerId);
    if (result.error) setError(result.error);
    else {
      setError(null);
      setData(result.data ?? null);
    }
    setLoading(false);
  }, [scope.brokerId]);

  useEffect(() => {
    if (scope.ready) void load();
  }, [scope.ready, load]);

  const act = async (kind: "accept" | "decline", handoffId: string) => {
    setNotice(null);
    const result =
      kind === "accept"
        ? await brokerApi.accept(handoffId, scope.brokerId)
        : await brokerApi.decline(handoffId, { broker_id: scope.brokerId, reason: "declined_from_today" });
    if (result.error) setNotice(result.error);
    else {
      setNotice(kind === "accept" ? "Handoff accepted — follow-ups cancelled." : "Handoff declined and re-routed.");
      void load();
    }
  };

  const counts = data?.counts;

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-8">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold">Broker Today</h1>
            <p className="mt-1 text-slate-600">{data?.date ?? ""} · new handoffs, hot leads, viewings and follow-ups due.</p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <Link href="/broker/pipeline" className="rounded-xl border bg-white px-4 py-2 font-medium hover:bg-slate-100">
              Pipeline
            </Link>
            {!scope.isAgent && (
              <label className="flex items-center gap-2 text-slate-600">
                Acting as broker
                <input
                  aria-label="Broker ID"
                  value={scope.brokerId ?? ""}
                  onChange={(e) => scope.setBrokerId(e.target.value)}
                  placeholder="all brokers"
                  className="w-44 rounded-lg border px-3 py-1.5 font-mono text-xs"
                />
              </label>
            )}
          </div>
        </header>

        {counts && (
          <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-6">
            {(
              [
                ["New handoffs", counts.new_handoffs],
                ["Accepted", counts.accepted],
                ["Hot leads", counts.hot_leads],
                ["Viewings", counts.viewings],
                ["Follow-ups due", counts.followups_due],
                ["Escalated", counts.escalated],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="rounded-xl border bg-white p-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
                <p className="mt-1 text-2xl font-semibold">{value}</p>
              </div>
            ))}
          </div>
        )}

        <div className="mt-4">
          <StatusBanner error={error} loading={loading && !data} />
          {notice && <p role="status" className="rounded-xl bg-blue-50 p-3 text-sm text-blue-800">{notice}</p>}
        </div>

        {data && (
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <Panel title="New handoffs" count={data.new_handoffs.length} empty="No pending handoffs.">
              {data.new_handoffs.map(({ handoff, lead }) =>
                lead ? (
                  <LeadCard key={handoff.id} lead={lead}>
                    <span className="mr-auto self-center text-xs text-slate-500">
                      {handoff.slot_text ? `Wants: ${handoff.slot_text} · ` : ""}
                      reassigns {relativeTime(handoff.reassign_after)}
                    </span>
                    <button onClick={() => act("accept", handoff.id)} className="rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white">
                      Accept
                    </button>
                    <button onClick={() => act("decline", handoff.id)} className="rounded-lg border px-3 py-1.5 text-xs font-semibold">
                      Decline
                    </button>
                  </LeadCard>
                ) : null
              )}
            </Panel>

            <Panel title="Hot leads" count={data.hot_leads.length} empty="No hot leads right now.">
              {data.hot_leads.map((lead) => <LeadCard key={lead.id} lead={lead} />)}
            </Panel>

            <Panel title="Accepted" count={data.accepted_handoffs.length} empty="Nothing accepted yet today.">
              {data.accepted_handoffs.map(({ handoff, lead }) =>
                lead ? (
                  <LeadCard key={handoff.id} lead={lead}>
                    <span className="text-xs text-slate-500">Accepted {relativeTime(handoff.accepted_at)}</span>
                  </LeadCard>
                ) : null
              )}
            </Panel>

            <Panel title="Follow-ups" count={data.followups.length} empty="No follow-ups scheduled.">
              {data.followups.map((f) => (
                <div key={f.id} className="flex items-center justify-between rounded-xl border bg-white p-3 text-sm">
                  <div>
                    <Link href={`/broker/leads/${f.lead_id}`} className="font-medium hover:underline">
                      {f.lead_name ?? f.lead_id}
                    </Link>
                    <p className="text-xs text-slate-500">
                      Touch {f.touch} · {f.template_key}
                    </p>
                  </div>
                  <span className="text-xs text-slate-500">due {relativeTime(f.due_at)}</span>
                </div>
              ))}
            </Panel>

            {data.escalated.length > 0 && (
              <Panel title="Escalated" count={data.escalated.length}>
                {data.escalated.map(({ handoff, lead }) =>
                  lead ? (
                    <LeadCard key={handoff.id} lead={lead}>
                      <span className="text-xs text-red-700">Reassigned {handoff.reassigned_count ?? 0}× — needs a manager</span>
                    </LeadCard>
                  ) : null
                )}
              </Panel>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
