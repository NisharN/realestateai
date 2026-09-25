"use client";

import { useCallback, useEffect, useState } from "react";
import { Bot, Cable, Database, Link2, MessageCircle, RefreshCw } from "lucide-react";
import { Badge, EmptyState, Section, Skeleton } from "@/components/ui/page";
import { coworkApi, type IntegrationCard } from "@/lib/api";
import { relativeTime } from "@/lib/broker-format";
import { ConnectorsTab, type Say } from "./ingestion-tools";
import { STATUS_LABEL, STATUS_TONE } from "./shared";

const KIND_ICON = {
  connector: Cable,
  channel: MessageCircle,
  ai: Bot,
  data: Database,
  crm: Link2,
} as const;

const KIND_LABEL = {
  connector: "CRM & lead sources",
  channel: "Messaging channels",
  ai: "AI providers",
  data: "Data",
  crm: "Real-estate CRM",
} as const;

const ORDER: IntegrationCard["kind"][] = ["crm", "connector", "channel", "ai", "data"];

export function IntegrationsTab({ say }: { say: Say }) {
  const [cards, setCards] = useState<IntegrationCard[] | null>(null);
  const [showConnectorTools, setShowConnectorTools] = useState(false);

  const load = useCallback(async () => {
    const r = await coworkApi.integrations();
    if (r.data) setCards(r.data.integrations);
    else say(r, "");
  }, [say]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!cards) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {ORDER.map((kind) => {
        const group = cards.filter((c) => c.kind === kind);
        if (group.length === 0 && kind !== "connector") return null;
        const Icon = KIND_ICON[kind];
        return (
          <section key={kind}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Icon className="h-4 w-4 text-brand" />
                {KIND_LABEL[kind]}
                <span className="ui-badge bg-muted text-muted-foreground tabular">{group.length}</span>
              </h2>
              {kind === "connector" && (
                <div className="flex items-center gap-2">
                  <button type="button" className="ui-btn-ghost ui-btn-sm" onClick={() => void load()}>
                    <RefreshCw className="h-3.5 w-3.5" /> Refresh
                  </button>
                  <button type="button" className="ui-btn-primary ui-btn-sm" onClick={() => setShowConnectorTools((v) => !v)}>
                    {showConnectorTools ? "Hide connector setup" : "Add or manage connectors"}
                  </button>
                </div>
              )}
            </div>
            {group.length === 0 ? (
              <EmptyState title="No lead sources connected" body="Add a CRM pull, webhook or CSV connector to start receiving leads." icon={<Cable className="h-5 w-5" />} />
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {group.map((card) => (
                  <IntegrationTile key={card.id} card={card} />
                ))}
              </div>
            )}
            {kind === "connector" && showConnectorTools && (
              <div className="mt-6">
                <Section title="Connector setup">
                  <ConnectorsTab say={say} />
                </Section>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

function IntegrationTile({ card }: { card: IntegrationCard }) {
  const dot = {
    connected: "bg-success",
    degraded: "bg-warning",
    not_configured: "bg-border",
    paused: "bg-border",
    error: "bg-danger",
  }[card.status];
  return (
    <article className="ui-card flex h-full flex-col p-4 transition hover:shadow-lg">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-foreground">{card.name}</p>
          {card.provider && <p className="truncate text-xs text-muted-foreground">{card.provider}</p>}
        </div>
        <Badge tone={STATUS_TONE[card.status]} className="shrink-0">
          <span className={`me-1.5 inline-block h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
          {STATUS_LABEL[card.status]}
        </Badge>
      </div>
      <p className="mt-3 flex-1 text-xs leading-relaxed text-muted-foreground">{card.detail}</p>
      <p className="mt-3 text-[11px] text-muted-foreground">
        {card.last_activity ? `Last activity ${relativeTime(card.last_activity)}` : "No activity yet"}
      </p>
    </article>
  );
}
