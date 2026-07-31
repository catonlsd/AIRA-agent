import { test, expect } from "@playwright/test";
import { seedFallback } from "./helpers";

test("operator: browser never requests or retains a privileged credential", async ({ page }) => {
  await seedFallback(page);
  await page.goto("/operator");

  await expect(
    page.getByRole("heading", { name: "Operator access is server-managed" }),
  ).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Connect" })).toHaveCount(0);

  const storage = await page.evaluate(() => ({
    local: Object.keys(window.localStorage),
    session: Object.keys(window.sessionStorage),
  }));
  expect(storage.local.some((key) => key.includes("operator"))).toBe(false);
  expect(storage.session.some((key) => key.includes("operator"))).toBe(false);
});
