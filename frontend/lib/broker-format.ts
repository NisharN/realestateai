import type { BrokerLeadSummary } from "./api";

export function formatAed(value: number | null | undefined): string | null {
  if (value == null) return null;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}k`;
  return value.toLocaleString("en-AE");
}

/** Budget text built only from stored values — never inferred. */
export function formatBudget(lead: Pick<BrokerLeadSummary, "budget_min_aed" | "budget_max_aed" | "budget_period">): string {
  const lo = formatAed(lead.budget_min_aed);
  const hi = formatAed(lead.budget_max_aed);
  if (!lo && !hi) return "Budget not stated";
  const range = lo && hi && lo !== hi ? `${lo}–${hi}` : `${hi ?? lo}`;
  const period = lead.budget_period === "year" ? "/yr" : lead.budget_period === "month" ? "/mo" : "";
  return `AED ${range}${period}`;
}

export function bandTone(band: string | null | undefined): string {
  switch (band) {
    case "hot":
      return "bg-red-100 text-red-700";
    case "warm":
      return "bg-amber-100 text-amber-700";
    case "cold":
      return "bg-slate-100 text-slate-600";
    default:
      return "bg-slate-100 text-slate-500";
  }
}

export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const mins = Math.round((now.getTime() - then) / 60_000);
  if (Math.abs(mins) < 1) return "just now";
  if (Math.abs(mins) < 60) return mins > 0 ? `${mins}m ago` : `in ${-mins}m`;
  const hours = Math.round(mins / 60);
  if (Math.abs(hours) < 48) return hours > 0 ? `${hours}h ago` : `in ${-hours}h`;
  const days = Math.round(hours / 24);
  return days > 0 ? `${days}d ago` : `in ${-days}d`;
}

export const STAGE_LABELS: Record<string, string> = {
  new: "New",
  qualifying: "Qualifying",
  qualified: "Qualified",
  handed_off: "Handed off",
  viewing_booked: "Viewing booked",
  offer: "Offer",
  closed: "Closed",
  lost: "Lost",
  opted_out: "Opted out",
};
