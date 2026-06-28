"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  getThemeForTime,
  isThemeName,
  msUntilNextTheme,
  type ThemeName,
} from "@/lib/timeTheme";

const STORAGE_KEY = "aira-x-theme";

type ThemeContextValue = {
  theme: ThemeName;
  autoTheme: ThemeName;
  isAuto: boolean;
  setOverride: (name: ThemeName | null) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readOverride(): ThemeName | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return isThemeName(value) ? value : null; // legacy light/dark/system -> Auto
  } catch {
    return null;
  }
}

function applyTheme(name: ThemeName) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  // night + phantom are the dark-scheme themes (drive the [data-scheme="dark"] rules).
  const dark = name === "night" || name === "phantom";

  root.dataset.theme = name; // palette
  root.dataset.scheme = dark ? "dark" : "light"; // coarse light/dark for component rules
  root.style.colorScheme = dark ? "dark" : "light";

  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  if (meta && bg) meta.content = bg;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [autoTheme, setAutoTheme] = useState<ThemeName>(() => getThemeForTime());
  const [override, setOverrideState] = useState<ThemeName | null>(null);

  // Server render had no storage access; hydrate the override after mount.
  useEffect(() => {
    setOverrideState(readOverride());
    setAutoTheme(getThemeForTime());
  }, []);

  const activeTheme = override ?? autoTheme;

  useEffect(() => {
    applyTheme(activeTheme);
  }, [activeTheme]);

  // Self-rescheduling boundary timer (no polling).
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        setAutoTheme(getThemeForTime());
        schedule();
      }, msUntilNextTheme());
    };
    schedule();
    return () => clearTimeout(timer);
  }, []);

  // Re-sync when the tab regains focus (laptop wake / long idle).
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") setAutoTheme(getThemeForTime());
    };
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, []);

  const setOverride = useCallback((name: ThemeName | null) => {
    setOverrideState(name);
    try {
      if (name) window.localStorage.setItem(STORAGE_KEY, name);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore storage failures; override still applies in memory.
    }
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: activeTheme,
      autoTheme,
      isAuto: override === null,
      setOverride,
    }),
    [activeTheme, autoTheme, override, setOverride],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used inside ThemeProvider");
  }
  return context;
}
