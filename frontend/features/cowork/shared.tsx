"use client";

import type { ReactNode } from "react";
import { Badge, type BadgeTone } from "@/components/ui/page";
import type { IntegrationStatus, JobRun } from "@/lib/api";

export const STATUS_TONE: Record<IntegrationStatus, BadgeTone> = {
  connected: "success",
  degraded: "warning",
  not_configured: "neutral",
  paused: "neutral",
  error: "danger",
};

export const STATUS_LABEL: Record<IntegrationStatus, string> = {
  connected: "Connected",
  degraded: "Degraded",
  not_configured: "Not configured",
  paused: "Paused",
  error: "Error",
};

export function RunStatus({ status }: { status: JobRun["status"] | "fired" | "failed" | string | null }) {
  const tone: BadgeTone = status === "success" || status === "fired" ? "success" : status === "failed" ? "danger" : status === "running" ? "brand" : "neutral";
  return <Badge tone={tone}>{status ?? "—"}</Badge>;
}

export function humanInterval(seconds: number): string {
  if (seconds % 86_400 === 0) return `${seconds / 86_400}d`;
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return `${seconds}s`;
}

export function summaryText(summary: Record<string, unknown> | string | null | undefined): string {
  if (!summary) return "";
  if (typeof summary === "string") return summary;
  const parts = Object.entries(summary)
    .filter(([, v]) => typeof v === "number" || typeof v === "string" || typeof v === "boolean")
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${String(v)}`);
  return parts.join(" · ");
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (next: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition disabled:opacity-50 ${checked ? "bg-brand" : "bg-border"}`}
    >
      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${checked ? "translate-x-5 rtl:-translate-x-5" : "translate-x-0.5 rtl:-translate-x-0.5"}`} />
    </button>
  );
}

export function Row({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`flex flex-wrap items-center gap-3 ${className}`}>{children}</div>;
}
