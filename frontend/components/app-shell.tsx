"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BookOpen,
  Building2,
  ClipboardList,
  KanbanSquare,
  LayoutDashboard,
  Map as MapIcon,
  Menu,
  MessageCircle,
  Settings2,
  Users,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import { authApi, type SessionContext } from "@/lib/api";
import { navigationForRole, type NavigationItem } from "@/lib/navigation";

const ICONS = {
  chat: MessageCircle,
  dashboard: LayoutDashboard,
  broker: ClipboardList,
  pipeline: KanbanSquare,
  cowork: Workflow,
  properties: Building2,
  market: MapIcon,
  automations: Zap,
  configure: Settings2,
  members: Users,
  docs: BookOpen,
};

const BARE_ROUTES = ["/login", "/forgot-password", "/reset-password", "/auth"];

function isActive(pathname: string, item: NavigationItem) {
  if (item.href === "/") return pathname === "/";
  if (item.href === "/broker") return pathname === "/broker" || pathname.startsWith("/broker/leads");
  return pathname.startsWith(item.href);
}

function SidebarNav({ items, pathname, onNavigate }: { items: NavigationItem[]; pathname: string; onNavigate?: () => void }) {
  const groups = [
    { label: "Workspace", keys: ["/dashboard", "/broker", "/broker/pipeline", "/properties", "/market"] },
    { label: "Operations", keys: ["/cowork"] },
    { label: "Settings", keys: ["/configure", "/members", "/docs"] },
  ];
  return (
    <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-5" aria-label="Primary">
      {groups.map((g) => {
        const entries = items.filter((i) => g.keys.includes(i.href));
        if (entries.length === 0) return null;
        return (
          <div key={g.label}>
            <p className="px-2.5 mb-1 text-[11px] font-medium text-muted-foreground/80">{g.label}</p>
            <ul className="space-y-px">
              {entries.map((item) => {
                const Icon = ICONS[item.icon];
                const active = isActive(pathname, item);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={
                        "group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors " +
                        (active
                          ? "bg-ink/[0.06] font-medium text-foreground"
                          : "text-muted-foreground hover:bg-ink/[0.04] hover:text-foreground")
                      }
                    >
                      <Icon className={"h-4 w-4 " + (active ? "text-brand" : "text-muted-foreground/70 group-hover:text-foreground")} />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function Brand() {
  return (
    <Link href="/dashboard" className="flex items-center gap-2.5 px-4 h-14">
      <div className="h-7 w-7 rounded-md bg-ink flex items-center justify-center">
        <Building2 className="h-3.5 w-3.5 text-white" />
      </div>
      <div className="leading-tight">
        <p className="text-[13px] font-semibold text-foreground tracking-tight">Dubai Real Estate AI</p>
        <p className="text-[11px] text-muted-foreground">Brokerage workspace</p>
      </div>
    </Link>
  );
}

function SidebarFooter({ session }: { session: SessionContext | null }) {
  return (
    <div className="border-t border-border p-3 space-y-2">
      <Link
        href="/"
        className="flex items-center gap-2.5 rounded-md border border-border bg-card px-2.5 py-2 text-[13px] text-foreground hover:bg-muted transition-colors"
      >
        <MessageCircle className="h-4 w-4 text-brand" />
        <span className="flex-1">Open buyer assistant</span>
      </Link>
      {session && (
        <div className="flex items-center gap-2.5 px-1.5 pt-1">
          <div className="h-7 w-7 rounded-full bg-gold-soft text-brand flex items-center justify-center text-xs font-semibold uppercase">
            {session.role.slice(0, 1)}
          </div>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-xs font-medium text-foreground">{session.broker_id ?? session.user_id.slice(0, 12)}</p>
            <p className="text-[11px] capitalize text-muted-foreground">{session.role}</p>
          </div>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [session, setSession] = useState<SessionContext | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    authApi.me().then(({ data }) => data && setSession(data));
  }, []);

  useEffect(() => setOpen(false), [pathname]);

  const bare = BARE_ROUTES.some((r) => pathname.startsWith(r)) || pathname === "/";
  if (bare) return <>{children}</>;

  const items = session ? navigationForRole(session.role) : [];

  return (
    <div className="flex min-h-screen bg-canvas">
      <aside className="hidden lg:flex w-60 shrink-0 flex-col border-e border-border bg-surface sticky top-0 h-screen">
        <Brand />
        <SidebarNav items={items} pathname={pathname} />
        <SidebarFooter session={session} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="lg:hidden sticky top-0 z-40 flex h-14 items-center justify-between border-b border-border bg-canvas/90 backdrop-blur px-4">
          <Link href="/dashboard" className="flex items-center gap-2 font-semibold text-sm">
            <div className="h-7 w-7 rounded-md bg-ink flex items-center justify-center">
              <Building2 className="h-3.5 w-3.5 text-white" />
            </div>
            Dubai Real Estate AI
          </Link>
          <button type="button" aria-label="Toggle navigation" onClick={() => setOpen((v) => !v)} className="ui-btn-ghost p-2">
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </header>
        {open && (
          <div className="lg:hidden fixed inset-0 z-30 flex">
            <div className="w-72 bg-surface border-e border-border flex flex-col">
              <Brand />
              <SidebarNav items={items} pathname={pathname} onNavigate={() => setOpen(false)} />
              <SidebarFooter session={session} />
            </div>
            <button type="button" aria-label="Close navigation" className="flex-1 bg-ink/30" onClick={() => setOpen(false)} />
          </div>
        )}
        <main className="flex-1 min-w-0">{children}</main>
      </div>
    </div>
  );
}
