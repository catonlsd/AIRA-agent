import { test, expect } from "@playwright/test";
import { seedFallback } from "./helpers";

test("operator: privileged operations are unavailable from browser UI", async ({ page }) => {
  await seedFallback(page);
  await page.goto("/operator");

  await expect(page.getByText("Restricted operations")).toBeVisible();
  await expect(page.getByText(/server-side administrative boundary/i)).toBeVisible();
  await expect(page.getByText("Delivery console")).toHaveCount(0);
});
