"use client";

/**
 * In-app documentation.
 *
 * The point of this page is honesty about what is real. An earlier version of
 * this product had a README claiming capabilities that didn't exist, plus a
 * dashboard showing fabricated leads under live stat cards. Anyone evaluating
 * this should be able to see, in the product itself, exactly which features
 * are wired to real services and which are running on seeded data.
 */

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Check, Circle, MinusCircle, XCircle } from "lucide-react";

type Status = "real" | "demo" | "gated" | "cut";

const STATUS_META: Record<
  Status,
  { label: string; cls: string; Icon: typeof Check }
> = {
  real: { label: "Real", cls: "bg-success-soft text-success", Icon: Check },
  demo: { label: "Seeded data", cls: "bg-warning-soft text-warning", Icon: Circle },
  gated: { label: "Deferred", cls: "bg-muted text-muted-foreground", Icon: MinusCircle },
  cut: { label: "Cut", cls: "bg-danger-soft text-danger", Icon: XCircle },
};

interface Row {
  feature: string;
  status: Status;
  detail: string;
}

const FEATURES: Row[] = [
  {
    feature: "Lead scoring & qualification",
    status: "real",
    detail:
      "Multi-agent pipeline scores intent and matches against real inventory in the store.",
  },
  {
    feature: "Budget & currency extraction",
    status: "real",
    detail:
      "Forces explicit currency (AED/USD) and period (total vs per-year). Asks a clarifying question instead of guessing — a bare \"1.2\" is never assumed to mean 1.2M.",
  },
  {
    feature: "Property matching",
    status: "real",
    detail:
      "Scores actual listings against stated preferences. Previously three hardcoded listings.",
  },
  {
    feature: "WhatsApp send",
    status: "demo",
    detail:
      "Real Meta Cloud API integration, running in simulation until Business Verification completes. Every message is recorded in the outbox so you can see exactly what would have gone out.",
  },
  {
    feature: "Scheduler (Celery + beat)",
    status: "real",
    detail:
      "Scheduled ingestion now actually executes. Previously the task fetched a schedule row and stopped at a comment, and no worker service existed to run it.",
  },
  {
    feature: "Reminders engine",
    status: "real",
    detail:
      "Five preset templates: new-lead follow-up, viewing reminders, post-viewing nudges, mandate renewals, listing staleness. Preview shows exactly what will run.",
  },
  {
    feature: "Listing refresh copy",
    status: "real",
    detail:
      "Generates a fresh, non-duplicate description for stale listings. Never posts to any portal — you copy and repost it yourself.",
  },
  {
    feature: "Market comps map",
    status: "demo",
    detail:
      "Leaflet + OpenStreetMap with Dubai Land Department transaction data. Sample rows by default; set DATA_MODE_DLD=live for real Dubai Pulse open data.",
  },
  {
    feature: "Dashboard & lead inbox",
    status: "real",
    detail:
      "Stats, pipeline board, leads table, and source mix all read the same API. No mock arrays.",
  },
  {
    feature: "Roles (owner / admin / agent)",
    status: "real",
    detail:
      "Enforced server-side. Agents see only leads assigned to their broker profile.",
  },
  {
    feature: "Billing (Stripe)",
    status: "real",
    detail: "Checkout and billing portal, owner-only, tied to workspace lifecycle.",
  },
  {
    feature: "Outbound voice",
    status: "gated",
    detail:
      "Deferred past the pilot. An English-only fence isn't safe when clients code-switch between Arabic and English mid-call. The approval gate ships now: no workflow can dial a lead without a human approving the first call, and there's a kill switch.",
  },
  {
    feature: "Portal enquiry import (Property Finder / Bayut)",
    status: "gated",
    detail:
      "Needs an authorised partner API — a business conversation before an engineering one. Enquiries must arrive through the brokerage's own account, CRM export, or approved API. Never harvested from another broker's account.",
  },
  {
    feature: "Visual workflow builder",
    status: "cut",
    detail:
      "Rejected. It rebuilds n8n by hand, contradicts a model where the customer pays specifically so they don't configure anything, and no agent opens a node editor between viewings. Preset templates instead.",
  },
  {
    feature: "Automated portal re-posting",
    status: "cut",
    detail:
      "Same terms-of-service exposure as scraping. A banned portal account would be an existential trust problem. Copy generation only.",
  },
  {
    feature: "Ejari / Form F pre-fill",
    status: "cut",
    detail:
      "Cut from the pilot. A checklist that organises required documents carries no liability; generating government-form content a broker might rubber-stamp does.",
  },
];

interface Health {
  workspace: string;
  tenancy: string;
  data_modes: Record<string, string>;
  voice_outbound: string;
  database: string;
  llm: string;
}

export default function DocsPage() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    fetch(`${base}/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-muted/50 p-6">
      <div className="max-w-4xl mx-auto">
        <header className="mb-8">
          <h1 className="text-2xl font-bold text-foreground">How this works</h1>
          <p className="text-sm text-muted-foreground mt-1">
            What&apos;s wired to real services, what&apos;s running on seeded data, and
            what was deliberately left out.
          </p>
        </header>

        {health && (
          <div className="bg-card rounded-2xl border border-border shadow-card p-6 mb-6">
            <h2 className="text-sm font-semibold text-foreground mb-4">
              This deployment
            </h2>
            <dl className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
              <Stat label="Workspace" value={health.workspace} />
              <Stat label="Tenancy" value={health.tenancy} />
              <Stat label="Database" value={health.database} />
              <Stat label="Properties" value={health.data_modes?.properties} />
              <Stat label="WhatsApp" value={health.data_modes?.whatsapp} />
              <Stat label="Market data" value={health.data_modes?.dld} />
            </dl>
          </div>
        )}

        <div className="bg-card rounded-2xl border border-border shadow-card divide-y divide-border/60 mb-8">
          {FEATURES.map((row, i) => {
            const meta = STATUS_META[row.status];
            const Icon = meta.Icon;
            return (
              <motion.div
                key={row.feature}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.02, 0.3) }}
                className="p-5"
              >
                <div className="flex items-center gap-3 mb-1.5">
                  <span
                    className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${meta.cls}`}
                  >
                    <Icon className="w-3 h-3" />
                    {meta.label}
                  </span>
                  <h3 className="text-sm font-semibold text-foreground">
                    {row.feature}
                  </h3>
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed">{row.detail}</p>
              </motion.div>
            );
          })}
        </div>

        <section className="bg-card rounded-2xl border border-border shadow-card p-6 mb-6">
          <h2 className="text-sm font-semibold text-foreground mb-3">
            Going live, source by source
          </h2>
          <p className="text-sm text-muted-foreground mb-4">
            Every external source has a mode switch. The default is offline demo
            data; each flips independently as its credentials and platform
            approvals land, so nothing blocks on the slowest one.
          </p>
          <div className="space-y-2 text-sm">
            <Timeline what="CSV / CRM import, manual entry, website forms" wait="No approval — works today" />
            <Timeline what="Google Sheets" wait="OAuth verification, 1-2 weeks" />
            <Timeline what="WhatsApp Business Cloud API" wait="Meta Business Verification, 2-4+ weeks" />
            <Timeline what="Meta / Instagram Lead Ads" wait="App Review + Business Verification, 2-4 weeks" />
            <Timeline what="Google Ads API" wait="Developer token review, 1-3 weeks" />
            <Timeline what="Gmail (read/send)" wait="Verification + CASA assessment, 4-8 weeks, paid" />
            <Timeline what="Property Finder / Bayut" wait="Partnership conversation, unbounded" />
          </div>
        </section>

        <p className="text-xs text-muted-foreground/70">
          Full scope, cuts, and rationale live in PILOT.md at the repository root.
        </p>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-foreground font-medium capitalize">{value ?? "—"}</dd>
    </div>
  );
}

function Timeline({ what, wait }: { what: string; wait: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 border-b border-gray-50 last:border-0">
      <span className="text-foreground/80">{what}</span>
      <span className="text-muted-foreground text-xs text-right flex-shrink-0">{wait}</span>
    </div>
  );
}
