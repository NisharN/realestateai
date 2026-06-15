"use client";

import { useState } from "react";
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
} from "lucide-react";

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
  icon: any;
}

// Mock data
const STATS: StatCard[] = [
  {
    title: "Total Leads",
    value: "1,284",
    change: "+12.5%",
    trend: "up",
    icon: Users,
  },
  {
    title: "Qualified Leads",
    value: "342",
    change: "+8.2%",
    trend: "up",
    icon: TrendingUp,
  },
  {
    title: "Properties Listed",
    value: "567",
    change: "+23.1%",
    trend: "up",
    icon: Building2,
  },
  {
    title: "Revenue Pipeline",
    value: "AED 45.2M",
    change: "+15.3%",
    trend: "up",
    icon: DollarSign,
  },
];

const MOCK_LEADS: Lead[] = [
  {
    id: "1",
    name: "Ahmed Al-Rashid",
    email: "ahmed@example.com",
    phone: "+971501234567",
    status: "qualified",
    intent_score: 85,
    source: "website",
    assigned_broker: "Sarah Johnson",
    created_at: "2024-01-15",
    budget: "AED 3-5M",
    area: "Downtown Dubai",
  },
  {
    id: "2",
    name: "Maria Gonzalez",
    email: "maria@example.com",
    phone: "+971502345678",
    status: "new",
    intent_score: 45,
    source: "whatsapp",
    assigned_broker: null,
    created_at: "2024-01-16",
    budget: "AED 1-2M",
    area: "Dubai Marina",
  },
  {
    id: "3",
    name: "Raj Patel",
    email: "raj@example.com",
    phone: "+971503456789",
    status: "contacted",
    intent_score: 72,
    source: "bayut",
    assigned_broker: "Ahmed Al-Rashid",
    created_at: "2024-01-14",
    budget: "AED 5M+",
    area: "Palm Jumeirah",
  },
  {
    id: "4",
    name: "Emma Wilson",
    email: "emma@example.com",
    phone: "+971504567890",
    status: "viewing_scheduled",
    intent_score: 92,
    source: "propertyfinder",
    assigned_broker: "Sarah Johnson",
    created_at: "2024-01-13",
    budget: "AED 2-3M",
    area: "Business Bay",
  },
  {
    id: "5",
    name: "Mohammed Khan",
    email: "mohammed@example.com",
    phone: "+971505678901",
    status: "negotiating",
    intent_score: 95,
    source: "referral",
    assigned_broker: "Ahmed Al-Rashid",
    created_at: "2024-01-10",
    budget: "AED 8M+",
    area: "Emirates Hills",
  },
];

const STATUS_COLORS: Record<string, string> = {
  new: "bg-gray-100 text-gray-700",
  qualified: "bg-blue-100 text-blue-700",
  contacted: "bg-yellow-100 text-yellow-700",
  viewing_scheduled: "bg-purple-100 text-purple-700",
  negotiating: "bg-orange-100 text-orange-700",
  closed_won: "bg-green-100 text-green-700",
  closed_lost: "bg-red-100 text-red-700",
  nurture: "bg-gray-100 text-gray-500",
};

const STATUS_LABELS: Record<string, string> = {
  new: "New",
  qualified: "Qualified",
  contacted: "Contacted",
  viewing_scheduled: "Viewing Scheduled",
  negotiating: "Negotiating",
  closed_won: "Closed Won",
  closed_lost: "Closed Lost",
  nurture: "Nurture",
};

function StatCardComponent({ stat }: { stat: StatCard }) {
  const Icon = stat.icon;
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-2xl p-6 border border-gray-100 shadow-sm"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="p-2 bg-blue-50 rounded-xl">
          <Icon className="w-5 h-5 text-blue-600" />
        </div>
        <div
          className={`flex items-center gap-1 text-xs font-medium ${
            stat.trend === "up" ? "text-green-600" : "text-red-600"
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
      <h3 className="text-2xl font-bold text-gray-900">{stat.value}</h3>
      <p className="text-sm text-gray-500 mt-1">{stat.title}</p>
    </motion.div>
  );
}

function PipelineBoard() {
  const columns = [
    { id: "new", label: "New", count: 12 },
    { id: "qualified", label: "Qualified", count: 8 },
    { id: "contacted", label: "Contacted", count: 6 },
    { id: "viewing_scheduled", label: "Viewing", count: 4 },
    { id: "negotiating", label: "Negotiating", count: 3 },
    { id: "closed_won", label: "Closed", count: 2 },
  ];

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="p-6 border-b border-gray-100">
        <h2 className="text-lg font-semibold text-gray-900">Pipeline Board</h2>
      </div>
      <div className="overflow-x-auto">
        <div className="flex gap-4 p-6 min-w-max">
          {columns.map((col) => (
            <div key={col.id} className="w-72 flex-shrink-0">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-gray-700">
                  {col.label}
                </h3>
                <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded-full">
                  {col.count}
                </span>
              </div>
              <div className="space-y-2">
                {MOCK_LEADS.filter((l) => l.status === col.id).map((lead) => (
                  <motion.div
                    key={lead.id}
                    whileHover={{ scale: 1.02 }}
                    className="p-3 bg-gray-50 rounded-xl border border-gray-100 cursor-pointer hover:shadow-md transition"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-gray-900">
                        {lead.name}
                      </span>
                      <span
                        className={`px-2 py-0.5 text-xs rounded-full ${
                          lead.intent_score >= 80
                            ? "bg-green-100 text-green-700"
                            : lead.intent_score >= 50
                            ? "bg-yellow-100 text-yellow-700"
                            : "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {lead.intent_score}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 text-xs text-gray-500 mb-1">
                      <MapPin className="w-3 h-3" />
                      {lead.area}
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500">{lead.budget}</span>
                      <span className="text-xs text-gray-400">
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

function LeadsTable() {
  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const filtered = MOCK_LEADS.filter((l) => {
    const matchesSearch =
      l.name.toLowerCase().includes(filter.toLowerCase()) ||
      l.email.toLowerCase().includes(filter.toLowerCase()) ||
      l.area.toLowerCase().includes(filter.toLowerCase());
    const matchesStatus =
      statusFilter === "all" || l.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="p-6 border-b border-gray-100">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">All Leads</h2>
          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search leads..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="pl-9 pr-4 py-2 bg-gray-100 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 w-64"
              />
            </div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 bg-gray-100 rounded-xl text-sm focus:outline-none"
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
            <tr className="border-b border-gray-100">
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                Lead
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                Status
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                Score
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                Source
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                Area
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                Budget
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                Broker
              </th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                Date
              </th>
              <th className="px-6 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((lead) => (
              <tr
                key={lead.id}
                className="border-b border-gray-50 hover:bg-gray-50/50 transition"
              >
                <td className="px-6 py-4">
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {lead.name}
                    </p>
                    <p className="text-xs text-gray-500">{lead.email}</p>
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
                    <div className="w-16 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          lead.intent_score >= 80
                            ? "bg-green-500"
                            : lead.intent_score >= 50
                            ? "bg-yellow-500"
                            : "bg-gray-400"
                        }`}
                        style={{ width: `${lead.intent_score}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-600">
                      {lead.intent_score}
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className="text-sm text-gray-600 capitalize">
                    {lead.source}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <span className="text-sm text-gray-600">{lead.area}</span>
                </td>
                <td className="px-6 py-4">
                  <span className="text-sm text-gray-600">{lead.budget}</span>
                </td>
                <td className="px-6 py-4">
                  <span className="text-sm text-gray-600">
                    {lead.assigned_broker || (
                      <span className="text-orange-500 text-xs">Unassigned</span>
                    )}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <span className="text-xs text-gray-500">
                    {new Date(lead.created_at).toLocaleDateString()}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <button className="p-1 hover:bg-gray-100 rounded-lg transition">
                    <MoreHorizontal className="w-4 h-4 text-gray-400" />
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

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="fixed left-0 top-0 h-full w-64 bg-white border-r border-gray-200 z-10">
        <div className="p-6">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-purple-600 rounded-xl flex items-center justify-center">
              <LayoutDashboard className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="font-bold text-gray-900">Dubai RE AI</h1>
              <p className="text-xs text-gray-500">Broker Dashboard</p>
            </div>
          </div>

          <nav className="space-y-1">
            {[
              { id: "overview", label: "Overview", icon: LayoutDashboard },
              { id: "pipeline", label: "Pipeline", icon: TrendingUp },
              { id: "leads", label: "All Leads", icon: Users },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id as any)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition ${
                    activeTab === item.id
                      ? "bg-blue-50 text-blue-700"
                      : "text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="absolute bottom-0 left-0 right-0 p-6 border-t border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gray-200 rounded-full flex items-center justify-center">
              <Users className="w-5 h-5 text-gray-500" />
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900">Sarah Johnson</p>
              <p className="text-xs text-gray-500">Senior Broker</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="ml-64 p-8">
        <div className="max-w-7xl mx-auto">
          {/* Header */}
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">
                {activeTab === "overview" && "Dashboard Overview"}
                {activeTab === "pipeline" && "Pipeline Board"}
                {activeTab === "leads" && "Lead Management"}
              </h1>
              <p className="text-sm text-gray-500 mt-1">
                {new Date().toLocaleDateString("en-US", {
                  weekday: "long",
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button className="px-4 py-2 bg-white border border-gray-200 text-gray-700 text-sm font-medium rounded-xl hover:bg-gray-50 transition">
                Export
              </button>
              <button className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700 transition">
                + New Lead
              </button>
            </div>
          </div>

          {/* Stats */}
          {activeTab === "overview" && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                {STATS.map((stat) => (
                  <StatCardComponent key={stat.title} stat={stat} />
                ))}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
                {/* Recent Activity */}
                <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
                  <h2 className="text-lg font-semibold text-gray-900 mb-4">
                    Recent Activity
                  </h2>
                  <div className="space-y-4">
                    {[
                      {
                        action: "New lead qualified",
                        detail: "Ahmed Al-Rashid - Downtown Dubai",
                        time: "2 min ago",
                        icon: Users,
                      },
                      {
                        action: "Site visit scheduled",
                        detail: "Maria Gonzalez - Dubai Marina",
                        time: "15 min ago",
                        icon: Calendar,
                      },
                      {
                        action: "Property scraped",
                        detail: "45 new listings from Bayut",
                        time: "1 hour ago",
                        icon: Building2,
                      },
                      {
                        action: "Deal closed",
                        detail: "Raj Patel - AED 8.5M villa",
                        time: "3 hours ago",
                        icon: DollarSign,
                      },
                    ].map((activity, i) => {
                      const Icon = activity.icon;
                      return (
                        <div key={i} className="flex items-start gap-3">
                          <div className="p-2 bg-blue-50 rounded-lg">
                            <Icon className="w-4 h-4 text-blue-600" />
                          </div>
                          <div className="flex-1">
                            <p className="text-sm font-medium text-gray-900">
                              {activity.action}
                            </p>
                            <p className="text-xs text-gray-500">
                              {activity.detail}
                            </p>
                          </div>
                          <span className="text-xs text-gray-400">
                            {activity.time}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Lead Sources */}
                <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
                  <h2 className="text-lg font-semibold text-gray-900 mb-4">
                    Lead Sources
                  </h2>
                  <div className="space-y-4">
                    {[
                      { source: "Website", count: 452, percentage: 35 },
                      { source: "WhatsApp", count: 312, percentage: 24 },
                      { source: "Bayut", count: 198, percentage: 15 },
                      { source: "PropertyFinder", count: 165, percentage: 13 },
                      { source: "Referrals", count: 98, percentage: 8 },
                      { source: "Other", count: 59, percentage: 5 },
                    ].map((item) => (
                      <div key={item.source}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm text-gray-700">
                            {item.source}
                          </span>
                          <span className="text-sm text-gray-500">
                            {item.count} ({item.percentage}%)
                          </span>
                        </div>
                        <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
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

          {activeTab === "pipeline" && <PipelineBoard />}
          {activeTab === "leads" && <LeadsTable />}
        </div>
      </main>
    </div>
  );
}
