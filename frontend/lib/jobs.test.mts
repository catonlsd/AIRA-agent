// Pure-logic tests for the background-job helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  hasActiveJobs,
  isActive,
  isTerminal,
  jobStatusLabel,
  jobTone,
  type Job,
  type JobStatus,
} from "./jobs.ts";

const job = (status: JobStatus): Job => ({
  id: "j1", kind: "artifact", status, title: "PPTX generation", progress: null,
  result: null, created_at: null, updated_at: null,
});

test("jobStatusLabel is human, never a raw enum", () => {
  assert.equal(jobStatusLabel("queued"), "Queued");
  assert.equal(jobStatusLabel("running"), "Working");
  assert.equal(jobStatusLabel("completed"), "Ready");
  assert.equal(jobStatusLabel("failed"), "Failed");
});

test("isActive / isTerminal partition the lifecycle", () => {
  assert.equal(isActive("queued"), true);
  assert.equal(isActive("validating"), true);
  assert.equal(isActive("completed"), false);
  assert.equal(isTerminal("completed"), true);
  assert.equal(isTerminal("failed"), true);
  assert.equal(isTerminal("running"), false);
});

test("jobTone warns on failure, accents while active, mutes when done", () => {
  assert.equal(jobTone("failed"), "warn");
  assert.equal(jobTone("running"), "accent");
  assert.equal(jobTone("completed"), "muted");
});

test("hasActiveJobs reflects whether anything is still working", () => {
  assert.equal(hasActiveJobs(null), false);
  assert.equal(hasActiveJobs([job("completed")]), false);
  assert.equal(hasActiveJobs([job("completed"), job("running")]), true);
});
