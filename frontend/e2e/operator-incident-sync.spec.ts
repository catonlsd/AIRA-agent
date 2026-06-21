import { test, expect } from "@playwright/test";
import { seedFallback, mockOperator, connectOperator, seedIncident } from "./helpers";

/**
 * Operator incident-sync flow (Step G): inspect a linked incident's external-sync
 * status and recheck it. Proves the incident → external-sync → refresh path holds
 * together in the browser. One high-value path, deterministic.
 */
test("operator: inspect a linked incident's external sync and refresh it", async ({ page }) => {
  await seedFallback(page);
  await mockOperator(page, { incidents: [seedIncident()] });
  await connectOperator(page);

  await page.getByRole("button", { name: "Incidents" }).click();
  // The seeded open incident is listed.
  await expect(page.getByText("stuck", { exact: false }).first()).toBeVisible();

  // Expand the incident's history/sync detail. NB: "History" is also a top nav tab —
  // the incident row's toggle is the LAST one in the DOM.
  await page.getByRole("button", { name: "History" }).last().click();

  // The external-sync linkage line shows the linked target + an Open link, with a
  // Refresh affordance for re-checking external state.
  await expect(page.getByText("Externally linked").first()).toBeVisible();
  const refresh = page.getByRole("button", { name: "Refresh" }).first();
  await expect(refresh).toBeVisible();
  await refresh.click();
  // After a recheck the linkage still renders (now with a checked timestamp).
  await expect(page.getByText(/checked/i).first()).toBeVisible();
});
