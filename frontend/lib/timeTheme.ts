// Time-adaptive theme engine. Pure + DOM-free so it is fully unit-testable.
// The 24h clock is bucketed into 6 named periods; the provider applies the result
// as data-theme="<name>" on <html>.

export type ThemeName =
  | "predawn"
  | "sunrise"
  | "daytime"
  | "dusk"
  | "sunset"
  | "night";

export const THEME_NAMES: readonly ThemeName[] = [
  "predawn",
  "sunrise",
  "daytime",
  "dusk",
  "sunset",
  "night",
] as const;

export const THEME_LABELS: Record<ThemeName, string> = {
  predawn: "Pre-dawn",
  sunrise: "Sunrise",
  daytime: "Daytime",
  dusk: "Dusk",
  sunset: "Sunset",
  night: "Night",
};

export function isThemeName(value: unknown): value is ThemeName {
  return (
    typeof value === "string" &&
    (THEME_NAMES as readonly string[]).includes(value)
  );
}

/** Period for the given local time. `night` is the fallback (wraps midnight). */
export function getThemeForTime(date: Date = new Date()): ThemeName {
  const totalMinutes = date.getHours() * 60 + date.getMinutes();
  if (totalMinutes >= 180 && totalMinutes <= 329) return "predawn"; // 03:00–05:29
  if (totalMinutes >= 330 && totalMinutes <= 479) return "sunrise"; // 05:30–07:59
  if (totalMinutes >= 480 && totalMinutes <= 1019) return "daytime"; // 08:00–16:59
  if (totalMinutes >= 1020 && totalMinutes <= 1109) return "dusk"; // 17:00–18:29
  if (totalMinutes >= 1110 && totalMinutes <= 1154) return "sunset"; // 18:30–19:14
  return "night"; // 19:15–02:59
}

/** Milliseconds until the next period boundary (drives a self-rescheduling timeout). */
export function msUntilNextTheme(date: Date = new Date()): number {
  const totalSeconds =
    date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds();
  const boundaries = [
    3 * 3600, // 03:00
    5 * 3600 + 30 * 60, // 05:30
    8 * 3600, // 08:00
    17 * 3600, // 17:00
    18 * 3600 + 30 * 60, // 18:30
    19 * 3600 + 15 * 60, // 19:15
  ];
  const daySeconds = 24 * 3600;
  for (const b of boundaries) {
    if (totalSeconds < b) return (b - totalSeconds) * 1000;
  }
  return (daySeconds - totalSeconds + 3 * 3600) * 1000; // tomorrow 03:00
}
