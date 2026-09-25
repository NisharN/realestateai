import { describe, expect, it } from "vitest";

import { navigationForRole } from "./navigation";

describe("navigationForRole", () => {
  it("hides administration from agents", () => {
    const hrefs = navigationForRole("agent").map((item) => item.href);
    expect(hrefs).toEqual(["/", "/dashboard", "/properties", "/market", "/automations"]);
    expect(hrefs).not.toContain("/configure");
    expect(hrefs).not.toContain("/members");
  });

  it("shows workspace administration to owners and admins", () => {
    expect(navigationForRole("admin").map((item) => item.href)).toContain("/configure");
    expect(navigationForRole("owner").map((item) => item.href)).toContain("/members");
  });
});
