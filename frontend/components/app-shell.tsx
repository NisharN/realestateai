"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BookOpen,
  Building2,
  ClipboardList,
  DatabaseZap,
  KanbanSquare,
  LayoutDashboard,
  Map as MapIcon,
  Menu,
  MessageCircle,
  Settings2,
  Users,
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
  ingestion: DatabaseZap,
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
    { label: "Data", keys: ["/admin/ingestion", "/automations"] },
    { label: "Settings", keys: ["/configure", "/members", "/docs"] },
  ];
  return (
    <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6" aria-label="Primary">
      {groups.map((g) => {
        const entries = items.filter((i) => g.keys.includes(i.href));
        if (entries.length === 0) return null;
        return (
          <div key={g.label}>
            <p className="px-3 mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-white/40">{g.label}</p>
            <ul className="space-y-0.5">
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
                        "group flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition " +
                        (active ? "bg-white/10 text-white shadow-inner" : "text-white/65 hover:bg-white/5 hover:text-white")
                      }
                    >
                      <Icon className={"h-4 w-4 " + (active ? "text-gold" : "text-white/50 group-hover:text-white/80")} />
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
    <Link href="/dashboard" className="flex items-center gap-3 px-5 h-16 border-b border-white/10">
      <div className="h-9 w-9 rounded-xl bg-gold/90 flex items-center justify-center shadow-pop">
        <Building2 className="h-[18px] w-[18px] text-ink" />
      </div>
      <div className="leading-tight">
        <p className="text-sm font-semibold text-white tracking-tight">Dubai Real Estate AI</p>
        <p className="text-[11px] text-white/45">Brokerage workspace</p>
      </div>
    </Link>
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
      <aside className="hidden lg:flex w-64 shrink-0 flex-col bg-ink-gradient text-white sticky top-0 h-screen">
        <Brand />
        <SidebarNav items={items} pathname={pathname} />
        <div className="border-t border-white/10 p-4">
          <Link href="/" className="flex items-center gap-3 rounded-xl bg-white/5 px-3 py-2.5 text-sm text-white/80 hover:bg-white/10 transition">
            <MessageCircle className="h-4 w-4 text-gold" />
            <span className="flex-1">Buyer assistant</span>
            <span className="text-[10px] uppercase tracking-wider text-white/40">Ali</span>
          </Link>
          {session && (
            <div className="mt-3 flex items-center gap-3 px-1">
              <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center text-xs font-semibold uppercase">
                {session.role.slice(0, 1)}
              </div>
              <div className="min-w-0 leading-tight">
                <p className="truncate text-xs font-medium text-white/90">{session.broker_id ?? session.user_id.slice(0, 12)}</p>
                <p className="text-[11px] capitalize text-white/45">{session.role}</p>
              </div>
            </div>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="lg:hidden sticky top-0 z-40 flex h-14 items-center justify-between border-b border-border bg-card/90 backdrop-blur px-4">
          <Link href="/dashboard" className="flex items-center gap-2 font-semibold text-sm">
            <div className="h-7 w-7 rounded-lg bg-brand flex items-center justify-center">
              <Building2 className="h-3.5 w-3.5 text-gold" />
            </div>
            Dubai Real Estate AI
          </Link>
          <button type="button" aria-label="Toggle navigation" onClick={() => setOpen((v) => !v)} className="ui-btn-ghost p-2">
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </header>
        {open && (
          <div className="lg:hidden fixed inset-0 z-30 flex">
            <div className="w-72 bg-ink-gradient text-white flex flex-col">
              <Brand />
              <SidebarNav items={items} pathname={pathname} onNavigate={() => setOpen(false)} />
            </div>
            <button type="button" aria-label="Close navigation" className="flex-1 bg-ink/40" onClick={() => setOpen(false)} />
          </div>
        )}
        <main className="flex-1 min-w-0">{children}</main>
      </div>
    </div>
  );
}
