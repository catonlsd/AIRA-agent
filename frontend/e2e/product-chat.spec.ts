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

test("app shell: mobile keeps navigation and chat usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await seedFallback(page);
  await page.goto("/chat");

  const sidebar = page.getByRole("complementary");
  const main = page.getByRole("main");
  const composer = page.getByPlaceholder("Message AIRA-X...");

  await expect(sidebar).toBeVisible();
  await expect(main).toBeVisible();
  await expect(composer).toBeVisible();

  const sidebarBox = await sidebar.boundingBox();
  const mainBox = await main.boundingBox();
  const composerBox = await composer.boundingBox();

  expect(sidebarBox?.width).toBeLessThanOrEqual(80);
  expect(mainBox?.width).toBeGreaterThanOrEqual(300);
  expect(composerBox?.x).toBeGreaterThanOrEqual(80);
  expect((composerBox?.x ?? 0) + (composerBox?.width ?? 0)).toBeLessThanOrEqual(390);
});

test("chat: focused composer is a dismissible, focus-contained dialog", async ({ page }) => {
  await seedFallback(page);
  await page.goto("/chat");
  await page.waitForLoadState("networkidle");

  const inlineComposer = page.getByPlaceholder("Message AIRA-X...");
  await inlineComposer.click();

  const dialog = page.getByRole("dialog", { name: "Focused prompt" });
  const focusedComposer = dialog.getByRole("textbox", { name: "Focused prompt" });
  const close = dialog.getByRole("button", { name: "Close" });
  const attach = dialog.getByRole("button", { name: "Attach a document" });

  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(focusedComposer).toBeFocused();

  await focusedComposer.press("Shift+Tab");
  await expect(close).toBeFocused();
  await close.press("Shift+Tab");
  await expect(attach).toBeFocused();

  await attach.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(inlineComposer).toBeFocused();
});
