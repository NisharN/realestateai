"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import {
  MessageCircle,
  LayoutDashboard,
  Settings2,
  BookOpen,
  Building2,
  Users,
  Map as MapIcon,
  Zap,
} from "lucide-react";
import { authApi } from "@/lib/api";
import { navigationForRole, type WorkspaceRole } from "@/lib/navigation";

const ICONS = {
  chat: MessageCircle,
  dashboard: LayoutDashboard,
  properties: Building2,
  market: MapIcon,
  automations: Zap,
  configure: Settings2,
  members: Users,
  docs: BookOpen,
};

export function Nav() {
  const pathname = usePathname();
  const [role, setRole] = useState<WorkspaceRole | null>(null);

  useEffect(() => {
    authApi.me().then(({ data }) => data && setRole(data.role));
  }, []);

  if (["/login", "/forgot-password", "/reset-password"].includes(pathname)) return null;
  const items = role ? navigationForRole(role) : [];

  return (
    <nav className="sticky top-0 z-40 bg-white/90 backdrop-blur border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 flex items-center justify-between h-14">
        <Link href="/" className="flex items-center gap-2 shrink-0">
          <div className="w-8 h-8 bg-gradient-to-br from-blue-600 to-purple-600 rounded-lg flex items-center justify-center">
            <Building2 className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-gray-900 text-sm hidden sm:inline">
            Dubai Real Estate AI
          </span>
          <span className="text-[10px] font-medium text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded-full">
            POC
          </span>
        </Link>

        <div className="flex items-center gap-1 relative">
          {items.map((item) => {
            const active = pathname === item.href;
            const Icon = ICONS[item.icon];
            return (
              <Link
                key={item.href}
                href={item.href}
                className="relative px-3 py-2 text-sm font-medium flex items-center gap-1.5 rounded-lg transition-colors"
              >
                {active && (
                  <motion.div
                    layoutId="nav-active-pill"
                    className="absolute inset-0 bg-blue-50 rounded-lg"
                    transition={{ type: "spring", stiffness: 400, damping: 32 }}
                  />
                )}
                <span
                  className={
                    "relative z-10 flex items-center gap-1.5 " +
                    (active ? "text-blue-700" : "text-gray-500 hover:text-gray-800")
                  }
                >
                  <Icon className="w-4 h-4" />
                  <span className="hidden sm:inline">{item.label}</span>
                </span>
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
