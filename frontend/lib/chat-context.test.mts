// Pure-logic tests for the chat-context helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  actionVerb,
  contextLabel,
  hasContext,
  hasItems,
  inChatActionLabel,
  itemsSummary,
  type AttachedContext,
} from "./chat-context.ts";

const ctx = (over: Partial<AttachedContext> = {}): AttachedContext => ({
  ref_type: "artifact",
  ref_id: "deck.pptx",
  title: "Roadmap Deck",
  action: "revise",
  summary: "PPTX artifact",
  prompt: 'Revise "Roadmap Deck": …',
  ...over,
});

test("contextLabel reads honestly per action", () => {
  assert.equal(contextLabel(ctx({ action: "revise" })), "Revising artifact: Roadmap Deck");
  assert.equal(contextLabel(ctx({ action: "use_as_context", ref_type: "document", title: "Q3.pdf" })), "Using document: Q3.pdf");
  assert.equal(contextLabel(ctx({ action: "continue_from", ref_type: "run", title: "Build RAG" })), "Continuing from run: Build RAG");
  assert.equal(contextLabel(ctx({ action: "resume", ref_type: "run", title: "Deck" })), "Resuming run: Deck");
  assert.equal(contextLabel(ctx({ action: "retry", ref_type: "run", title: "Job" })), "Retrying run: Job");
});

test("actionVerb maps each action", () => {
  assert.equal(actionVerb("revise"), "Revising artifact");
  assert.equal(actionVerb("resume"), "Resuming run");
});

test("inChatActionLabel is honest and consistent per resource", () => {
  assert.equal(inChatActionLabel("document"), "Use in chat");
  assert.equal(inChatActionLabel("artifact"), "Revise");
  assert.equal(inChatActionLabel("run", "resume"), "Resume");
  assert.equal(inChatActionLabel("run", "retry"), "Retry");
  assert.equal(inChatActionLabel("run", "continue_from"), "Continue");
});

test("hasContext reflects whether something is attached", () => {
  assert.equal(hasContext(null), false);
  assert.equal(hasContext(ctx()), true);
});

test("itemsSummary collapses to one label or a count", () => {
  assert.equal(itemsSummary([]), "");
  assert.equal(itemsSummary([ctx({ action: "revise", title: "Deck" })]), "Revising artifact: Deck");
  assert.equal(itemsSummary([ctx(), ctx({ ref_id: "b.pptx" }), ctx({ ref_id: "c.pptx" })]), "Using 3 items");
});

test("hasItems reflects whether the attached set is non-empty", () => {
  assert.equal(hasItems(null), false);
  assert.equal(hasItems([]), false);
  assert.equal(hasItems([ctx()]), true);
});
