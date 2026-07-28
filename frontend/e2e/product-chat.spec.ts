import { test, expect } from "@playwright/test";
import { seedFallback, mockStream, answerFinal, fillInteractiveForm } from "./helpers";

/**
 * Core product flow (Step D): a user asks a question in the real browser app, the
 * streamed response renders, and the turn resolves to a final answer. The backend is
 * stubbed deterministically — this proves the browser product path, not a helper fn.
 */
test("chat: ask a question and see the streamed answer resolve", async ({ page }) => {
  await seedFallback(page);
  await mockStream(page, {
    tokens: ["AIRA-X is ", "online and ", "grounded."],
    final: answerFinal("AIRA-X is online and grounded."),
  });

  await page.goto("/chat");
  const composer = page.getByPlaceholder("Message AIRA-X...");
  await expect(composer).toBeVisible();
  await fillInteractiveForm(
    composer,
    "Are you online?",
    composer.locator("xpath=ancestor::form[1]").getByRole("button", { name: "Send" }),
  );
  await composer.press("Enter");

  // The user's question echoes, and the streamed answer renders in the answer card.
  await expect(page.getByText("Are you online?")).toBeVisible();
  await expect(page.getByText("AIRA-X is online and grounded.")).toBeVisible();
});
