import { describe, expect, it } from "vitest";

import { formatBudget, relativeTime } from "./broker-format";

describe("formatBudget", () => {
  it("never invents a budget", () => {
    expect(formatBudget({ budget_min_aed: null, budget_max_aed: null, budget_period: null })).toBe("Budget not stated");
  });
  it("renders stored ranges and yearly rent", () => {
    expect(formatBudget({ budget_min_aed: 1_000_000, budget_max_aed: 1_500_000, budget_period: "total" })).toBe("AED 1M–1.5M");
    expect(formatBudget({ budget_min_aed: null, budget_max_aed: 120_000, budget_period: "year" })).toBe("AED 120k/yr");
  });
});

describe("relativeTime", () => {
  it("handles past, future and missing values", () => {
    const now = new Date("2026-01-01T12:00:00Z");
    expect(relativeTime("2026-01-01T11:30:00Z", now)).toBe("30m ago");
    expect(relativeTime("2026-01-01T12:15:00Z", now)).toBe("in 15m");
    expect(relativeTime(null, now)).toBe("—");
  });
});
