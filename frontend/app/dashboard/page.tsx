"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  LayoutDashboard,
  Users,
  Building2,
  Phone,
  TrendingUp,
  DollarSign,
  MapPin,
  Calendar,
  ArrowUpRight,
  ArrowDownRight,
  Filter,
  Search,
  MoreHorizontal,
  type LucideIcon,
} from "lucide-react";
import { Copilot } from "@/components/copilot";
import {
  dashboardApi,
  leadsApi,
  type ApiLead,
  type DashboardSummary,
} from "@/lib/api";

// Types
interface Lead {
  id: string;
  name: string;
  email: string;
  phone: string;
  status: string;
  intent_score: number;
  source: string;
  assigned_broker: string | null;
  created_at: string;
  budget: string;
  area: string;
}

interface StatCard {
  title: string;
  value: string;
  change: string;
  trend: "up" | "down";
  icon: LucideIcon;
}

/** Map an API lead onto the shape this dashboard renders. */
function toDashboardLead(lead: ApiLead): Lead {
  const name = [lead.first_name, lead.last_name].filter(Boolean).join(" ").trim();
  return {
    id: lead.id,
    name: name || "Unnamed lead",
    email: lead.email ?? "",
    phone: lead.phone ?? "",
    status: lead.status ?? "new",
    intent_score: lead.intent_score ?? 0,
    source: lead.source ?? "unknown",
    assigned_broker: lead.assigned_broker ?? null,
    created_at: lead.created_at ?? "",
    budget: formatBudget(lead),
    area: lead.area_preference?.[0] ?? "—",
  };
}

/** Render a budget without inventing a currency or period we weren't told. */
function formatBudget(lead: ApiLead): string {
  const { budget_min: min, budget_max: max } = lead;
  if (!min && !max) return "Not stated";
  const currency = lead.budget_currency ?? "AED";
  const suffix =
    lead.budget_period === "year"
      ? "/yr"
      : lead.budget_period === "month"
      ? "/mo"
      : "";
  const compact = (value: number) =>
    value >= 1_000_000
      ? `${(value / 1_000_000).toFixed(1)}M`
      : `${Math.round(value / 1000)}K`;
  if (min && max && min !== max) {
    return `${currency} ${compact(min)}-${compact(max)}${suffix}`;
  }
  return `${currency} ${compact((max ?? min) as number)}${suffix}`;
}


// These must match the statuses the backend actually stores (see
// api/leads.py list_leads) — otherwise a lead renders with a blank status pill.
const STATUS_COLORS: Record<string, string> = {
  new: "bg-muted text-foreground/80",
  contacted: "bg-yellow-100 text-yellow-700",
  qualified: "bg-brand/10 text-brand",
  nurture: "bg-purple-100 text-purple-600",
  closed: "bg-success-soft text-success",
  lost: "bg-danger-soft text-danger",
};

const STATUS_LABELS: Record<string, string> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  nurture: "Nurture",
  closed: "Closed",
  lost: "Lost",
};

function StatCardComponent({ stat }: { stat: StatCard }) {
  const Icon = stat.icon;
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-card rounded-2xl p-6 border border-border shadow-card"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="p-2 bg-brand/5 rounded-xl">
          <Icon className="w-5 h-5 text-brand" />
        </div>
        <div
          className={`flex items-center gap-1 text-xs font-medium ${
            stat.trend === "up" ? "text-success" : "text-danger"
          }`}
        >
          {stat.trend === "up" ? (
            <ArrowUpRight className="w-3 h-3" />
          ) : (
            <ArrowDownRight className="w-3 h-3" />
          )}
          {stat.change}
        </div>
      </div>
      <h3 className="text-2xl font-bold text-foreground">{stat.value}</h3>
      <p className="text-sm text-muted-foreground mt-1">{stat.title}</p>
    </motion.div>
  );
}

/** Real source mix, derived from the loaded leads rather than hardcoded. */
function leadSourceBreakdown(
  leads: Lead[]
): { source: string; count: number; percentage: number }[] {
  if (leads.length === 0) return [];
  const counts = new Map<string, number>();
  for (const lead of leads) {
    const label = SOURCE_LABELS[lead.source] ?? lead.source;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([source, count]) => ({
      source,
      count,
      percentage: Math.round((count / leads.length) * 100),
    }))
    .sort((a, b) => b.count - a.count);
}

const SOURCE_LABELS: Record<string, string> = {
  propertyfinder: "Property Finder",
  bayut: "Bayut",
  whatsapp: "WhatsApp",
  website_form: "Website",
  crm_import: "CRM import",
  referral: "Referral",
  walk_in: "Walk-in",
  instagram: "Instagram",
  google_ads: "Google Ads",
};

function LoadingPanel({ label }: { label: string }) {
  return (
    <div className="bg-card rounded-2xl border border-border shadow-card p-12 text-center">
      <div className="inline-block w-6 h-6 border-2 border-border border-t-blue-600 rounded-full animate-spin mb-3" />
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

function PipelineBoard({ leads }: { leads: Lead[] }) {
  // Columns and their counts both come from the same live lead list. They used
  // to be hardcoded, which meant the board could show "12 New" above zero
  // actual cards — the inconsistency a broker would spot immediately.
  const columns = [
    { id: "new", label: "New" },
    { id: "contacted", label: "Contacted" },
    { id: "qualified", label: "Qualified" },
    { id: "nurture", label: "Nurture" },
    { id: "closed", label: "Closed" },
    { id: "lost", label: "Lost" },
  ];

  return (
    <div className="bg-card rounded-2xl border border-border shadow-card overflow-hidden">
      <div className="p-6 border-b border-border">
        <h2 className="text-lg font-semibold text-foreground">Pipeline Board</h2>
      </div>
      <div className="overflow-x-auto">
        <div className="flex gap-4 p-6 min-w-max">
          {columns.map((col) => (
            <div key={col.id} className="w-72 flex-shrink-0">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-foreground/80">
                  {col.label}
                </h3>
                <span className="px-2 py-0.5 bg-muted text-muted-foreground text-xs rounded-full">
                  {leads.filter((l) => l.status === col.id).length}
                </span>
              </div>
              <div className="space-y-2">
                {leads.filter((l) => l.status === col.id).map((lead) => (
                  <motion.div
                    key={lead.id}
                    whileHover={{ scale: 1.02 }}
                    className="p-3 bg-muted/50 rounded-xl border border-border cursor-pointer hover:shadow-md transition"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-foreground">
                        {lead.name}
                      </span>
                      <span
                        className={`px-2 py-0.5 text-xs rounded-full ${
                          lead.intent_score >= 80
                            ? "bg-success-soft text-success"
                            : lead.intent_score >= 50
                            ? "bg-yellow-100 text-yellow-700"
                            : "bg-muted text-muted-foreground"
                        }`}
                      >
                        {lead.intent_score}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 text-xs text-muted-foreground mb-1">
                      <MapPin className="w-3 h-3" />
                      {lead.area}
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">{lead.budget}</span>
                      <span className="text-xs text-muted-foreground/70">
                        {lead.assigned_broker || "Unassigned"}
                      </span>
                    </div>
                  </motion.div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function LeadsTable({ leads }: { leads: Lead[] }) {
  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const filtered = leads.filter((l) => {
    const matchesSearch =
      l.name.toLowerCase().includes(filter.toLowerCase()) ||
      l.email.toLowerCase().includes(filter.toLowerCase()) ||
      l.area.toLowerCase().includes(filter.toLowerCase());
    const matchesStatus =
      statusFilter === "all" || l.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="bg-card rounded-2xl border border-border shadow-card overflow-hidden">
      <div className="p-6 border-b border-border">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-foreground">All Leads</h2>
          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70" />
              <input
                type="text"
                placeholder="Search leads..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="pl-9 pr-4 py-2 bg-muted rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand/20 w-64"
              />
            </div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 bg-muted rounded-xl text-sm focus:outline-none"
            >
              <option value="all">All Status</option>
              {Object.entries(STATUS_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-6 py-3 text-xs font-medium text-muted-foreground uppercase">
                Lead
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-muted-foreground uppercase">
                Status
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-muted-foreground uppercase">
                Score
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-muted-foreground uppercase">
                Source
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-muted-foreground uppercase">
                Area
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-muted-foreground uppercase">
                Budget
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-muted-foreground uppercase">
                Broker
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-muted-foreground uppercase">
                Date
              </th>
              <th className="px-6 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((lead) => (
              <tr
                key={lead.id}
                className="border-b border-gray-50 hover:bg-muted/50/50 transition"
              >
                <td className="px-6 py-4">
                  <div>
                    <p className="text-sm font-medium text-foreground">
                      {lead.name}
                    </p>
                    <p className="text-xs text-muted-foreground">{lead.email}</p>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span
                    className={`px-2.5 py-1 text-xs font-medium rounded-full ${
                      STATUS_COLORS[lead.status]
                    }`}
                  >
                    {STATUS_LABELS[lead.status]}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-2 bg-muted rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          lead.intent_score >= 80
                            ? "bg-green-500"
                            : lead.intent_score >= 50
                            ? "bg-yellow-500"
                            : "bg-muted-foreground"
                        }`}
                        style={{ width: `${lead.intent_score}%` }}
                      />
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {lead.intent_score}
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className="text-sm text-muted-foreground capitalize">
                    {lead.source}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <span className="text-sm text-muted-foreground">{lead.area}</span>
                </td>
                <td className="px-6 py-4">
                  <span className="text-sm text-muted-foreground">{lead.budget}</span>
                </td>
                <td className="px-6 py-4">
                  <span className="text-sm text-muted-foreground">
                    {lead.assigned_broker || (
                      <span className="text-orange-500 text-xs">Unassigned</span>
                    )}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <span className="text-xs text-muted-foreground">
                    {new Date(lead.created_at).toLocaleDateString()}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <button className="p-1 hover:bg-muted rounded-lg transition">
                    <MoreHorizontal className="w-4 h-4 text-muted-foreground/70" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<"overview" | "pipeline" | "leads">(
    "overview"
  );
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [leadsError, setLeadsError] = useState<string | null>(null);
  const [leadsLoading, setLeadsLoading] = useState(true);

  useEffect(() => {
    let active = true;
    dashboardApi.summary().then((result) => {
      if (!active) return;
      if (result.data) setSummary(result.data);
      else setSummaryError(result.error ?? "Unable to load dashboard");
    });
    return () => {
      active = false;
    };
  }, []);

  // The pipeline board and leads table used to render a hardcoded MOCK_LEADS
  // array directly beneath live stat cards — so the counts were real but the
  // rows underneath them were fiction. Both now read the same API.
  useEffect(() => {
    let active = true;
    leadsApi.list({ limit: 100 }).then((result) => {
      if (!active) return;
      setLeadsLoading(false);
      if (result.data) setLeads(result.data.map(toDashboardLead));
      else setLeadsError(result.error ?? "Unable to load leads");
    });
    return () => {
      active = false;
    };
  }, []);

  const stats: StatCard[] = [
    { title: "Total Leads", value: summary?.total_leads.toLocaleString() ?? "—", change: "Live", trend: "up", icon: Users },
    { title: "Qualified Leads", value: summary?.qualified_leads.toLocaleString() ?? "—", change: "Live", trend: "up", icon: TrendingUp },
    { title: "Closed Leads", value: summary?.closed_leads.toLocaleString() ?? "—", change: "Live", trend: "up", icon: Building2 },
    { title: "Average Intent", value: summary ? `${summary.average_intent_score}%` : "—", change: "Live", trend: "up", icon: DollarSign },
  ];

  return (
    <div className="px-5 py-8 lg:px-10">
      <main>
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
            <div>
              <p className="ui-kicker">
                {new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
              </p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">
                {activeTab === "overview" && "Dashboard overview"}
                {activeTab === "pipeline" && "Pipeline board"}
                {activeTab === "leads" && "Lead management"}
              </h1>
            </div>
            <div className="inline-flex rounded-xl border border-border bg-card p-1 shadow-card" role="tablist">
              {(
                [
                  { id: "overview", label: "Overview", icon: LayoutDashboard },
                  { id: "pipeline", label: "Pipeline", icon: TrendingUp },
                  { id: "leads", label: "All leads", icon: Users },
                ] as const
              ).map((item) => {
                const Icon = item.icon;
                const active = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    role="tab"
                    aria-selected={active}
                    onClick={() => setActiveTab(item.id)}
                    className={`flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition ${
                      active ? "bg-brand text-white shadow-card" : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    }`}
                  >
                    <Icon className="w-4 h-4" />
                    {item.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Stats */}
          {activeTab === "overview" && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                {summaryError && (
                  <div role="alert" className="md:col-span-2 lg:col-span-4 rounded-xl bg-danger-soft p-4 text-sm text-danger">
                    {summaryError}
                  </div>
                )}
                {stats.map((stat) => (
                  <StatCardComponent key={stat.title} stat={stat} />
                ))}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 mb-8">
                <div className="lg:col-span-3">
                  <Copilot />
                </div>

                {/* Lead Sources */}
                <div className="lg:col-span-2 bg-card rounded-2xl border border-border shadow-card p-6">
                  <h2 className="text-lg font-semibold text-foreground mb-4">
                    Lead Sources
                  </h2>
                  <div className="space-y-4">
                    {leadSourceBreakdown(leads).map((item) => (
                      <div key={item.source}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm text-foreground/80">
                            {item.source}
                          </span>
                          <span className="text-sm text-muted-foreground">
                            {item.count} ({item.percentage}%)
                          </span>
                        </div>
                        <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full transition-all"
                            style={{ width: `${item.percentage}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}

          {leadsError && activeTab !== "overview" && (
            <div className="mb-4 px-4 py-3 rounded-xl bg-warning-soft border border-warning/20 text-sm text-warning">
              {leadsError}
            </div>
          )}
          {activeTab === "pipeline" &&
            (leadsLoading ? <LoadingPanel label="Loading pipeline…" /> : <PipelineBoard leads={leads} />)}
          {activeTab === "leads" &&
            (leadsLoading ? <LoadingPanel label="Loading leads…" /> : <LeadsTable leads={leads} />)}
        </div>
      </main>
    </div>
  );
}
