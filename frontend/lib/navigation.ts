export type WorkspaceRole = "owner" | "admin" | "agent";

export interface NavigationItem {
  href: string;
  label: string;
  icon:
    | "chat"
    | "dashboard"
    | "broker"
    | "pipeline"
    | "cowork"
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
 * Market comps and automations are in the common set deliberately — an agent
 * arguing price with a landlord needs comps, and needs to see what the
 * automation already sent their lead before they pick up the phone.
 */
const common: NavigationItem[] = [
  { href: "/", label: "Chat", icon: "chat" },
  { href: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { href: "/broker", label: "Today", icon: "broker" },
  { href: "/broker/pipeline", label: "Pipeline", icon: "pipeline" },
  { href: "/properties", label: "Properties", icon: "properties" },
  { href: "/market", label: "Market", icon: "market" },
  { href: "/automations", label: "Automations", icon: "automations" },
];

export function navigationForRole(role: WorkspaceRole): NavigationItem[] {
  if (role === "agent") return common;
  return [
    ...common,
    { href: "/cowork", label: "Co-work", icon: "cowork" },
    { href: "/configure", label: "Configure", icon: "configure" },
    { href: "/members", label: "Members", icon: "members" },
    { href: "/docs", label: "Docs", icon: "docs" },
  ];
}
