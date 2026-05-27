"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from "react";

export type AiraOperatingMode = "aira" | "aira-x";

type ModeContextValue = {
  mode: AiraOperatingMode;
  setMode: (mode: AiraOperatingMode) => void;
};

const ModeContext = createContext<ModeContextValue | null>(null);

const STORAGE_KEY = "aira-operating-mode";
const UNIFIED_MODE: AiraOperatingMode = "aira-x";

export function ModeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, UNIFIED_MODE);
    document.documentElement.dataset.airaMode = UNIFIED_MODE;

    return () => {
      delete document.documentElement.dataset.airaMode;
    };
  }, []);

  function setMode(_nextMode: AiraOperatingMode) {
    window.localStorage.setItem(STORAGE_KEY, UNIFIED_MODE);
    document.documentElement.dataset.airaMode = UNIFIED_MODE;
  }

  const value = useMemo(
    () => ({
      mode: UNIFIED_MODE,
      setMode,
    }),
    []
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