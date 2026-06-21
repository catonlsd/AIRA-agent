import { test, expect } from "@playwright/test";
import { API, seedFallback, answerFinal, planFinal } from "./helpers";

/**
 * Core execution / approval flow (Step E): a build request returns a plan awaiting
 * approval, the operator approves, and the turn resolves. The stream endpoint is
 * stubbed STATEFULLY — first call returns the plan, the approval re-submit returns the
 * completed result — so the whole approve round-trip is deterministic.
 */
test("chat: plan-ready turn shows approval and resolves after approving", async ({ page }) => {
  await seedFallback(page);

  // SSE helper inline so we can vary the response by call count.
  let calls = 0;
  await page.route(`${API}/aira-x/stream`, (route) => {
    calls += 1;
    const final = calls === 1 ? planFinal("Here is my plan.") : answerFinal("Done — executed the plan.");
    const body =
      `event: token\ndata: ${JSON.stringify({ text: calls === 1 ? "Here is my plan." : "Done — executed the plan." })}\n\n` +
      `event: final\ndata: ${JSON.stringify(final)}\n\n`;
    return route.fulfill({ status: 200, contentType: "text/event-stream", body });
  });

  await page.goto("/chat");
  const composer = page.getByPlaceholder("Message AIRA-X...");
  await composer.fill("Generate and validate a deck");
  await composer.press("Enter");

  // The plan-approval affordance appears.
  const approve = page.getByRole("button", { name: "Approve plan & execute" });
  await expect(approve).toBeVisible();

  // Approving sends the go-ahead (second stream) and the turn resolves.
  await approve.click();
  await expect(page.getByText("Done — executed the plan.")).toBeVisible();
  await expect(approve).toHaveCount(0);
});
