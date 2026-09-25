import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

export function Page({ children, width = "max-w-7xl" }: { children: ReactNode; width?: string }) {
  return (
    <div className="px-5 py-8 lg:px-10">
      <div className={`mx-auto ${width}`}>{children}</div>
    </div>
  );
}

export function PageHeader({
  kicker,
  title,
  description,
  actions,
}: {
  kicker?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {kicker && <p className="ui-kicker mb-1.5">{kicker}</p>}
        <h1 className="text-[28px] font-semibold leading-tight text-foreground">{title}</h1>
        {description && <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function StatCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "brand" | "success" | "warning" | "danger";
}) {
  const accent = {
    default: "bg-border",
    brand: "bg-brand",
    success: "bg-success",
    warning: "bg-warning",
    danger: "bg-danger",
  }[tone];
  return (
    <div className="ui-card relative overflow-hidden p-4">
      <span className={`absolute inset-y-4 start-0 w-1 rounded-e ${accent}`} aria-hidden />
      <p className="ui-kicker ps-2">{label}</p>
      <p className="tabular mt-2 ps-2 text-2xl font-semibold text-foreground">{value}</p>
      {hint && <p className="mt-1 ps-2 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function Badge({ children, tone = "neutral", className = "" }: { children: ReactNode; tone?: BadgeTone; className?: string }) {
  return <span className={`ui-badge ${BADGE_TONES[tone]} ${className}`}>{children}</span>;
}

export type BadgeTone = "neutral" | "brand" | "success" | "warning" | "danger" | "gold";

export const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: "bg-muted text-muted-foreground",
  brand: "bg-brand/10 text-brand",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  gold: "bg-gold-soft text-warning",
};

export function EmptyState({ title, body, icon }: { title: string; body?: string; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-card/60 px-6 py-10 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">{icon ?? <Inbox className="h-5 w-5" />}</div>
      <p className="text-sm font-medium text-foreground">{title}</p>
      {body && <p className="mt-1 max-w-xs text-xs text-muted-foreground">{body}</p>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-muted ${className}`} aria-hidden />;
}

export function Section({ title, count, actions, children }: { title: ReactNode; count?: number; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="ui-card overflow-hidden">
      <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          {title}
          {count != null && <span className="ui-badge bg-muted text-muted-foreground tabular">{count.toLocaleString("en-US")}</span>}
        </h2>
        {actions}
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}
