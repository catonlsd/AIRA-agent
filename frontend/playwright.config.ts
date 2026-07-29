import { defineConfig, devices } from "@playwright/test";

/**
 * Deterministic E2E config (Phase 3).
 *
 * The suite is intentionally small and HERMETIC: every test stubs the backend at the
 * network layer (`page.route`), so there is no real API, no LLM, no database, and no
 * third-party calls. We exercise the REAL Next.js app (routing, components, operator
 * key flow, readiness rendering, streaming render) against seeded API responses — the
 * gap the backend wall can't cover. Chromium only, to stay fast and CI-friendly.
 */
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  timeout: 30_000,
  expect: { timeout: 7_000 },
  use: {
    baseURL: "http://localhost:3100",
    trace: "on-first-retry",
    // The app's API base is baked at build time (default http://localhost:8000); the
    // tests intercept by URL glob, so the host is irrelevant.
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
