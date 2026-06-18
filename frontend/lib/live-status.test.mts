// Pure-logic tests for the unified live-status helpers. Node's built-in runner.
import { test } from "node:test";
import assert from "node:assert/strict";

import { isLiveJob, isResolved, jobLivePhase, liveBannerLabel } from "./live-status.ts";
import type { Job, JobStatus } from "./jobs.ts";

const job = (status: JobStatus, over: Partial<Job> = {}): Job => ({
  id: "j1", kind: "artifact", status, title: "PPTX generation", progress: null,
  result: null, created_at: null, updated_at: null, ...over,
});

test("jobLivePhase prefers the server phase, then falls back by status", () => {
  // Server-computed phase wins.
  assert.equal(jobLivePhase(job("running", { phase: { key: "validating", label: "Running validation", tone: "active" } })).label, "Running validation");
  // Fallback maps status to the shared vocabulary.
  assert.equal(jobLivePhase(job("running")).label, "Working in the background");
  assert.equal(jobLivePhase(job("completed")).label, "Completed");
  assert.equal(jobLivePhase(job("canceled")).tone, "warn");
  // A just-queued retry reads honestly.
  assert.equal(jobLivePhase(job("queued", { origin: "retry" })).label, "Retrying");
});

test("isLiveJob is true only for non-terminal work", () => {
  assert.equal(isLiveJob(job("running")), true);
  assert.equal(isLiveJob(job("queued")), true);
  assert.equal(isLiveJob(job("completed")), false);
  assert.equal(isLiveJob(job("failed")), false);
  assert.equal(isLiveJob(job("canceled")), false);
});

test("liveBannerLabel summarizes active work calmly", () => {
  assert.equal(liveBannerLabel([job("completed")]), null);
  assert.equal(liveBannerLabel([job("running")]), "Working in the background");
  assert.equal(liveBannerLabel([job("running"), job("queued"), job("completed")]), "Working in the background · 2 tasks");
});

test("isResolved reflects terminal reconciliation", () => {
  assert.equal(isResolved({ state: "active" }), false);
  assert.equal(isResolved({ state: "terminal" }), true);
});
