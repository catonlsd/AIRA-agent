// Pure-logic tests for the time-adaptive theme engine. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  getThemeForTime,
  msUntilNextTheme,
  isThemeName,
  THEME_NAMES,
  THEME_LABELS,
} from "./timeTheme.ts";

const at = (h: number, m: number, s = 0) => new Date(2026, 0, 1, h, m, s);

test("getThemeForTime maps every segment incl. boundaries", () => {
  assert.equal(getThemeForTime(at(2, 59)), "night");
  assert.equal(getThemeForTime(at(3, 0)), "predawn");
  assert.equal(getThemeForTime(at(5, 29)), "predawn");
  assert.equal(getThemeForTime(at(5, 30)), "sunrise");
  assert.equal(getThemeForTime(at(7, 59)), "sunrise");
  assert.equal(getThemeForTime(at(8, 0)), "daytime");
  assert.equal(getThemeForTime(at(16, 59)), "daytime");
  assert.equal(getThemeForTime(at(17, 0)), "dusk");
  assert.equal(getThemeForTime(at(18, 29)), "dusk");
  assert.equal(getThemeForTime(at(18, 30)), "sunset");
  assert.equal(getThemeForTime(at(19, 14)), "sunset");
  assert.equal(getThemeForTime(at(19, 15)), "night");
  assert.equal(getThemeForTime(at(23, 59)), "night");
  assert.equal(getThemeForTime(at(0, 0)), "night");
});

test("msUntilNextTheme returns ms to the next boundary", () => {
  assert.equal(msUntilNextTheme(at(2, 0, 0)), 60 * 60 * 1000); // → 03:00
  assert.equal(msUntilNextTheme(at(4, 0, 0)), 90 * 60 * 1000); // → 05:30
  assert.equal(msUntilNextTheme(at(7, 59, 30)), 30 * 1000); // → 08:00
});

test("msUntilNextTheme wraps past the last boundary to tomorrow 03:00", () => {
  assert.equal(msUntilNextTheme(at(20, 0, 0)), 7 * 60 * 60 * 1000); // 20:00 → 03:00 next day
  assert.equal(msUntilNextTheme(at(0, 0, 0)), 3 * 60 * 60 * 1000); // 00:00 → 03:00 same day
});

test("isThemeName validates and rejects legacy values", () => {
  assert.equal(isThemeName("daytime"), true);
  assert.equal(isThemeName("night"), true);
  assert.equal(isThemeName("dark"), false);
  assert.equal(isThemeName("system"), false);
  assert.equal(isThemeName(null), false);
  assert.equal(isThemeName(42), false);
});

test("THEME_NAMES and THEME_LABELS cover all six periods", () => {
  assert.equal(THEME_NAMES.length, 6);
  for (const name of THEME_NAMES) {
    assert.equal(typeof THEME_LABELS[name], "string");
  }
});
