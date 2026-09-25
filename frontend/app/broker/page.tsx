"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { brokerApi, type BrokerToday } from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";
import { useBrokerScope } from "@/lib/use-broker-scope";
import { LeadCard, Panel, StatusBanner } from "@/components/broker/lead-card";
import { Badge, Page, PageHeader, StatCard, StatStrip } from "@/components/ui/page";
import { CalendarClock, Phone } from "lucide-react";

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
    <Page>
      <PageHeader
        kicker={data?.date ?? "Today"}
        title="Broker Today"
        description="New handoffs, hot leads, viewings and follow-ups due — everything that needs a call today."
        actions={
          <>
            <Link href="/broker/pipeline" className="ui-btn-secondary">
              Pipeline
            </Link>
            {!scope.isAgent && (
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                Acting as
                <input
                  aria-label="Broker ID"
                  value={scope.brokerId ?? ""}
                  onChange={(e) => scope.setBrokerId(e.target.value)}
                  placeholder="all brokers"
                  className="ui-input w-40 font-mono text-xs"
                />
              </label>
            )}
          </>
        }
      />

      {counts && (
        <StatStrip className="mt-6">
          <StatCard label="New handoffs" value={counts.new_handoffs.toLocaleString("en-US")} tone={counts.new_handoffs ? "brand" : "default"} />
          <StatCard label="Accepted" value={counts.accepted.toLocaleString("en-US")} />
          <StatCard label="Hot leads" value={counts.hot_leads.toLocaleString("en-US")} tone={counts.hot_leads ? "danger" : "default"} />
          <StatCard label="Viewings" value={counts.viewings.toLocaleString("en-US")} />
          <StatCard label="Follow-ups due" value={counts.followups_due.toLocaleString("en-US")} tone={counts.followups_due ? "warning" : "default"} />
          <StatCard label="Escalated" value={counts.escalated.toLocaleString("en-US")} tone={counts.escalated ? "danger" : "default"} />
        </StatStrip>
      )}

      <div className="mt-4 space-y-3">
        <StatusBanner error={error} loading={loading && !data} />
        {notice && (
          <p role="status" className="rounded-xl border border-success/20 bg-success-soft p-3 text-sm text-success">
            {notice}
          </p>
        )}
      </div>

        {data && (
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <Panel title="New handoffs" count={data.new_handoffs.length} empty="No pending handoffs.">
              {data.new_handoffs.map(({ handoff, lead }) =>
                lead ? (
                  <LeadCard key={handoff.id} lead={lead}>
                    <span className="me-auto flex items-center gap-1 text-xs text-muted-foreground"><CalendarClock className="h-3.5 w-3.5" />
                      {handoff.slot_text ? `Wants: ${handoff.slot_text} · ` : ""}
                      reassigns {relativeTime(handoff.reassign_after)}
                    </span>
                    <button onClick={() => act("accept", handoff.id)} className="ui-btn-primary ui-btn-sm">
                      <Phone className="h-3.5 w-3.5" /> Accept
                    </button>
                    <button onClick={() => act("decline", handoff.id)} className="ui-btn-secondary ui-btn-sm">
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
                    <span className="text-xs text-muted-foreground">Accepted {relativeTime(handoff.accepted_at)}</span>
                  </LeadCard>
                ) : null
              )}
            </Panel>

            <Panel title="Viewings" count={data.viewings.length} empty="No viewings requested or booked.">
              {data.viewings.map((v) => (
                <div key={v.id} className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card p-3 text-sm">
                  <div>
                    <Link href={`/broker/leads/${v.lead_id}`} className="font-medium hover:text-brand">
                      Lead {v.lead_id.slice(0, 8)}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      {v.starts_at
                        ? new Date(v.starts_at).toLocaleString("en-AE", { timeZone: "Asia/Dubai", dateStyle: "medium", timeStyle: "short" })
                        : "time TBC"}
                      {v.property_id ? ` · property ${v.property_id}` : ""} · via {v.source}
                    </p>
                  </div>
                  <Badge tone={v.status === "confirmed" ? "success" : v.status === "done" ? "brand" : "neutral"} className="capitalize">{v.status}</Badge>
                </div>
              ))}
            </Panel>

            <Panel title="Follow-ups" count={data.followups.length} empty="No follow-ups scheduled.">
              {data.followups.map((f) => (
                <div key={f.id} className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card p-3 text-sm">
                  <div>
                    <Link href={`/broker/leads/${f.lead_id}`} className="font-medium hover:text-brand">
                      {f.lead_name ?? f.lead_id}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      Touch {f.touch} · {f.template_key}
                    </p>
                  </div>
                  <span className="text-xs text-muted-foreground">due {relativeTime(f.due_at)}</span>
                </div>
              ))}
            </Panel>

            {data.escalated.length > 0 && (
              <Panel title="Escalated" count={data.escalated.length}>
                {data.escalated.map(({ handoff, lead }) =>
                  lead ? (
                    <LeadCard key={handoff.id} lead={lead}>
                      <span className="text-xs text-danger">Reassigned {handoff.reassigned_count ?? 0}× — needs a manager</span>
                    </LeadCard>
                  ) : null
                )}
              </Panel>
            )}
          </div>
        )}
    </Page>
  );
}
