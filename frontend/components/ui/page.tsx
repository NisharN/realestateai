import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

export function Page({ children, width = "max-w-7xl" }: { children: ReactNode; width?: string }) {
  return (
    <div className="px-5 py-7 lg:px-10 lg:py-9">
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
        <h1 className="font-display text-[34px] leading-none text-foreground">{title}</h1>
        {description && <p className="mt-2 max-w-[60ch] text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function StatStrip({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`grid grid-cols-2 gap-px overflow-hidden border-y border-border bg-border md:grid-cols-3 xl:grid-cols-6 [&>*]:bg-canvas ${className}`}>
      {children}
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
  tone = "default",
  onClick,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "brand" | "success" | "warning" | "danger";
  onClick?: () => void;
}) {
  const valueTone = {
    default: "text-foreground",
    brand: "text-brand",
    success: "text-success",
    warning: "text-warning",
    danger: "text-danger",
  }[tone];
  const body = (
    <>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`tabular mt-1 text-[22px] font-semibold leading-none ${valueTone}`}>{value}</p>
      {hint && <p className="mt-1.5 truncate text-xs text-muted-foreground">{hint}</p>}
    </>
  );
  const cls = "min-w-[150px] flex-1 px-5 py-3 text-start first:ps-0";
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={`${cls} rounded-md transition-colors hover:bg-ink/[0.03]`}>
        {body}
      </button>
    );
  }
  return <div className={cls}>{body}</div>;
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
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-10 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">{icon ?? <Inbox className="h-5 w-5" />}</div>
      <p className="text-sm font-medium text-foreground">{title}</p>
      {body && <p className="mt-1 max-w-xs text-xs text-muted-foreground">{body}</p>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-muted ${className}`} aria-hidden />;
}

export function Section({ title, count, actions, children }: { title: ReactNode; count?: number; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="ui-card overflow-hidden">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-medium text-foreground">
          {title}
          {count != null && <span className="tabular text-xs text-muted-foreground">{count.toLocaleString("en-US")}</span>}
        </h2>
        {actions}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}
