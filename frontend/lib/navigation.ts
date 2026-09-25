export type WorkspaceRole = "owner" | "admin" | "agent";

export interface NavigationItem {
  href: string;
  label: string;
  icon:
    | "chat"
    | "dashboard"
    | "broker"
    | "pipeline"
    | "connections"
    | "crm"
    | "routines"
    | "insights"
    | "properties"
    | "market"
    | "automations"
    | "configure"
    | "members"
    | "docs";
}

/**
 * Single-tenant deployment: roles scope what a user sees *within* one
 * brokerage. Agents get the day-to-day working set; owners and admins
 * additionally get configuration, team management, and docs.
 *
 * Operations (connections, CRM, routines, insights) is in the common set: the
 * product is built for individual agents who connect their own portals,
 * WhatsApp and CRM. Event rules and the job scheduler live under its Advanced menu.
 */
const common: NavigationItem[] = [
  { href: "/", label: "Chat", icon: "chat" },
  { href: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { href: "/broker", label: "Today", icon: "broker" },
  { href: "/broker/pipeline", label: "Pipeline", icon: "pipeline" },
  { href: "/properties", label: "Properties", icon: "properties" },
  { href: "/market", label: "Market", icon: "market" },
  { href: "/cowork/connections", label: "Connections", icon: "connections" },
  { href: "/cowork/crm", label: "CRM", icon: "crm" },
  { href: "/cowork/routines", label: "Routines", icon: "routines" },
  { href: "/cowork/insights", label: "Insights", icon: "insights" },
];

export function navigationForRole(role: WorkspaceRole): NavigationItem[] {
  if (role === "agent") return common;
  return [
    ...common,
    { href: "/configure", label: "Configure", icon: "configure" },
    { href: "/members", label: "Members", icon: "members" },
    { href: "/docs", label: "Docs", icon: "docs" },
  ];
}
