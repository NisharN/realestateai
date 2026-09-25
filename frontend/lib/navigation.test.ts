import { describe, expect, it } from "vitest";

import { navigationForRole } from "./navigation";

describe("navigationForRole", () => {
  it("gives agents the working set including Operations, but not administration", () => {
    const hrefs = navigationForRole("agent").map((item) => item.href);
    expect(hrefs).toEqual(["/", "/dashboard", "/broker", "/broker/pipeline", "/properties", "/market", "/cowork/connections", "/cowork/crm", "/cowork/routines", "/cowork/insights"]);
    expect(hrefs).not.toContain("/automations");
    expect(hrefs).not.toContain("/configure");
    expect(hrefs).not.toContain("/members");
  });

  it("shows workspace administration to owners and admins", () => {
    expect(navigationForRole("admin").map((item) => item.href)).toContain("/configure");
    expect(navigationForRole("admin").map((item) => item.href)).toContain("/cowork/routines");
    expect(navigationForRole("owner").map((item) => item.href)).toContain("/members");
  });
});
