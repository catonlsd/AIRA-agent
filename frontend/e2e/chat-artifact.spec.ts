import { test, expect } from "@playwright/test";
import { seedFallback, mockStream, artifactFinal, fillInteractiveForm } from "./helpers";

/**
 * Core artifact flow (Step H): a build request resolves to a downloadable artifact
 * card with a working download affordance. Deterministic — the artifact comes from a
 * seeded final, not real (slow, non-deterministic) generation.
 */
test("chat: a build request renders an artifact card with a download link", async ({ page }) => {
  await seedFallback(page);
  await mockStream(page, {
    tokens: ["Built your deck."],
    final: artifactFinal("Built your deck."),
  });

  await page.goto("/chat");
  const composer = page.getByPlaceholder("Message AIRA-X...");
  await fillInteractiveForm(
    composer,
    "Build me a quarterly review deck",
    page.locator("button.aira-send-btn:visible"),
  );
  await composer.press("Enter");

  // The artifact card renders with its title and a download link to the real endpoint.
  await expect(page.locator("p.artifact-title")).toHaveText("Quarterly Review Deck");
  const download = page.locator("a.artifact-download");
  await expect(download).toBeVisible();
  await expect(download).toHaveAttribute("href", /\/artifacts\/quarterly-review\.pptx/);
});
