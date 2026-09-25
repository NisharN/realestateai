import { expect, test, type Page } from "@playwright/test";

const INPUT_EN = "Ask about properties, areas, prices...";
const INPUT_AR = "اسأل عن العقارات والمناطق والأسعار...";

async function send(page: Page, text: string, placeholder = INPUT_EN) {
  const before = await page.locator("[data-role='assistant']").count();
  const input = page.getByPlaceholder(placeholder);
  await input.fill(text);
  await input.press("Enter");
  await expect(page.locator("[data-role='assistant']")).toHaveCount(before + 1);
  return page.locator("[data-role='assistant']").last();
}

test.describe("buyer chat (demo mode, template replies)", () => {
  test("qualifies a buyer, shows property cards and offers a specialist call", async ({ page }) => {
    await page.goto("/");
    await page.getByPlaceholder(INPUT_EN).waitFor();

    const first = await send(page, "I want to buy a 2 bed apartment in Dubai Marina");
    await expect(first).toContainText(/budget/i);

    await send(page, "around 2.5 million");
    await expect(page.getByTestId("property-card").first()).toBeVisible();

    const confirm = await send(page, "within 3 months, cash");
    await expect(confirm).toContainText(/specialist/i);

    const done = await send(page, "yes please");
    await expect(done).toContainText(/call you|in touch/i);
  });

  test("every turn gets a reply, including gibberish", async ({ page }) => {
    await page.goto("/");
    await page.getByPlaceholder(INPUT_EN).waitFor();
    const reply = await send(page, "asdkjh qwe zxc");
    await expect(reply).not.toBeEmpty();
  });

  test("Arabic input flips the layout to RTL and replies in Arabic", async ({ page }) => {
    await page.goto("/");
    await page.getByPlaceholder(INPUT_EN).waitFor();
    const reply = await send(page, "مرحبا، أبحث عن شقة غرفتين في مرسى دبي للشراء");
    await expect(reply).toContainText(/[\u0600-\u06FF]/);
    await expect(page.locator("[dir='rtl'][lang='ar']").first()).toBeVisible();
    await expect(page.getByPlaceholder(INPUT_AR)).toBeVisible();
  });

  test("STOP opts the buyer out and disables further replies", async ({ page }) => {
    await page.goto("/");
    await page.getByPlaceholder(INPUT_EN).waitFor();
    await send(page, "buy a 2 bed in marina");
    const reply = await send(page, "STOP");
    await expect(reply).toContainText(/won.t message you again/i);
  });
});
