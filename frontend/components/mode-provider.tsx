"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type AiraOperatingMode = "aira" | "aira-x";

type ModeContextValue = {
  mode: AiraOperatingMode;
  setMode: (mode: AiraOperatingMode) => void;
};

const ModeContext = createContext<ModeContextValue | null>(null);

const STORAGE_KEY = "aira-operating-mode";

function getStoredMode(): AiraOperatingMode {
  if (typeof window === "undefined") {
    return "aira-x";
  }

  const storedMode = window.localStorage.getItem(STORAGE_KEY);

  if (storedMode === "aira" || storedMode === "aira-x") {
    return storedMode;
  }

  return "aira-x";
}

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<AiraOperatingMode>("aira-x");

  useEffect(() => {
    setModeState(getStoredMode());
  }, []);

  function setMode(nextMode: AiraOperatingMode) {
    setModeState(nextMode);
    window.localStorage.setItem(STORAGE_KEY, nextMode);
  }

  const value = useMemo(
    () => ({
      mode,
      setMode,
    }),
    [mode]
  );

  return <ModeContext.Provider value={value}>{children}</ModeContext.Provider>;
}

export function useAiraMode() {
  const context = useContext(ModeContext);

  if (!context) {
    throw new Error("useAiraMode must be used inside ModeProvider");
  }

  return context;
}
