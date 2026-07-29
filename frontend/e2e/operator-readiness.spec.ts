import { test, expect } from "@playwright/test";
import {
  seedFallback,
  mockOperator,
  connectOperator,
  seedTarget,
  API,
  fillInteractiveForm,
} from "./helpers";

/**
 * Operator target-readiness flow (Step F) — the strongest commercial signal.
 * Connect with the operator key, find a configured-but-unverified target, validate it
 * (→ Ready), and send a safe synthetic test. Proves AIRA-X is an operable system, not
 * just "AI chat." Fully stubbed: no real targets, no external calls.
 */

test.beforeEach(async ({ page }) => {
  await seedFallback(page);
});

test("operator: connect, validate a target to Ready, then safe test-send", async ({ page }) => {
  await mockOperator(page, { targets: [seedTarget()] });
  await connectOperator(page);

  // Incidents tab hosts the External-sync panel with the targets.
  await page.getByRole("button", { name: "Incidents" }).click();
  await expect(page.getByText("PagerDuty (prod)")).toBeVisible();
  // Starts Unverified. "Unverified" also appears in the Phase-4 attention rollup chip,
  // so scope to the target row's readiness badge (last occurrence in the panel).
  await expect(page.getByText("Unverified").last()).toBeVisible();

  // Validate → readiness flips to Ready.
  await page.getByRole("button", { name: "Validate" }).click();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible();

  // Safe synthetic test-send → success flash.
  await page.getByRole("button", { name: "Test" }).click();
  await expect(page.getByText("Test event sent.")).toBeVisible();
});

test("operator: console requires the service key (operator separation)", async ({ page }) => {
  // Overview rejects an unknown key → the console never renders.
  await page.route(`${API}/operator/overview`, (r) => r.fulfill({ status: 403, body: "{}" }));
  await page.goto("/operator");
  await expect(page.getByRole("heading", { name: "Operator console" })).toBeVisible();
  const connect = page.getByRole("button", { name: "Connect" });
  await fillInteractiveForm(page.getByPlaceholder("Service key"), "wrong-key", connect);
  await connect.click();
  await expect(page.getByText("That service key was not accepted.")).toBeVisible();
  // The delivery console (operator-only) is NOT reachable.
  await expect(page.getByRole("heading", { name: "Delivery console" })).toHaveCount(0);
});
