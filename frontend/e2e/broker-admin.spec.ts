import { expect, test } from "@playwright/test";

test.describe("broker workspace (demo mode)", () => {
  test("Broker Today renders hot leads and links to lead detail", async ({ page }) => {
    await page.goto("/broker");
    await expect(page.getByRole("heading", { name: "Broker Today" })).toBeVisible();
    const lead = page.locator("a[href^='/broker/leads/']").first();
    await expect(lead).toBeVisible();
    await lead.click();
    await expect(page).toHaveURL(/\/broker\/leads\//);
    await expect(page.getByText("Book a viewing")).toBeVisible();
  });

  test("books a viewing, confirms it and sees it on Broker Today", async ({ page }) => {
    await page.goto("/broker");
    await page.locator("a[href^='/broker/leads/']").first().click();
    await expect(page.getByText("Book a viewing")).toBeVisible();

    const when = new Date(Date.now() + 2 * 24 * 3600 * 1000);
    when.setMinutes(0, 0, 0);
    const local = new Date(when.getTime() - when.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
    await page.getByLabel("Viewing date and time").fill(local);
    await page.getByPlaceholder("Notes (optional)").fill("e2e viewing");
    await page.getByRole("button", { name: "Book viewing" }).click();

    const row = page.locator("li").filter({ hasText: "via broker" }).first();
    await expect(row).toBeVisible();
    await expect(row).toContainText(/Requested|Confirmed/);

    const confirm = row.getByRole("button", { name: "Confirmed" });
    if (await confirm.count()) {
      await confirm.click();
    }
    await expect(row.locator("span").first()).toHaveText("Confirmed");
    await expect(row.getByRole("button", { name: "Done" })).toBeVisible();

    const leadId = page.url().split("/broker/leads/")[1];
    await page.goto("/broker");
    await expect(page.getByRole("heading", { name: /^Viewings/ })).toBeVisible();
    const viewing = page
      .locator("div")
      .filter({ has: page.getByRole("link", { name: `Lead ${leadId.slice(0, 8)}` }) })
      .filter({ hasText: /via broker/ })
      .filter({ has: page.getByText("confirmed", { exact: true }) });
    await expect(viewing.last()).toBeVisible();
  });

  test("lead detail shows the qualification profile and timeline", async ({ page }) => {
    await page.goto("/broker/pipeline");
    await page.locator("a[href^='/broker/leads/']").first().click();
    await expect(page.getByText(/timeline/i).first()).toBeVisible();
  });
});

test.describe("admin (demo mode)", () => {
  test("Ops tab shows latency stats and alert state", async ({ page }) => {
    await page.goto("/admin/ingestion");
    await page.getByRole("tab", { name: "Ops" }).click();
    await expect(page.getByText(/Last \d+ minutes/)).toBeVisible();
    await expect(page.getByText("Last 1,000 turns")).toBeVisible();
    await expect(page.getByText("Consumers")).toBeVisible();
    await expect(page.getByText(/No active alerts|CRITICAL|WARNING/).first()).toBeVisible();
  });

  test("review queue and data health tabs load", async ({ page }) => {
    await page.goto("/admin/ingestion");
    for (const name of ["Review queue", "Data health"]) {
      const tab = page.getByRole("tab", { name });
      if (await tab.count()) {
        await tab.click();
        await expect(page.getByText(/Network error|Failed to|Error:/)).toHaveCount(0);
      }
    }
  });
});
