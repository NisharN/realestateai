import { describe, expect, it } from "vitest";

import { navigationForRole } from "./navigation";

describe("navigationForRole", () => {
  it("hides administration from agents", () => {
    expect(navigationForRole("agent").map((item) => item.href)).toEqual([
      "/",
      "/dashboard",
      "/properties",
    ]);
  });

  it("shows workspace administration to owners and admins", () => {
    expect(navigationForRole("admin").map((item) => item.href)).toContain("/configure");
    expect(navigationForRole("owner").map((item) => item.href)).toContain("/members");
  });
});
