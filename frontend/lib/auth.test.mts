// Pure-logic tests for the auth helpers. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import { authHeaders, isAuthenticated } from "./auth.ts";

test("authHeaders attaches a bearer token when present", () => {
  assert.deepEqual(authHeaders("abc.def"), { Authorization: "Bearer abc.def" });
});

test("authHeaders is empty (safe to spread) when signed out", () => {
  assert.deepEqual(authHeaders(null), {});
  assert.deepEqual(authHeaders(undefined), {});
  assert.deepEqual(authHeaders(""), {});
});

test("isAuthenticated reflects token presence", () => {
  assert.equal(isAuthenticated("tok"), true);
  assert.equal(isAuthenticated(null), false);
  assert.equal(isAuthenticated(""), false);
});
