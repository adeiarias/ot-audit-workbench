import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Mode = "light" | "dark" | "system";
export const PRESETS = [
  { value: "audit", label: "Audit", swatch: ["#2D2A26", "#22C5E0"] },
  { value: "neutral", label: "Neutro", swatch: ["#1a1a1a", "#e5e5e5"] },
  { value: "soft-pop", label: "Soft Pop", swatch: ["#4f46e5", "#f59e0b"] },
  { value: "tangerine", label: "Tangerine", swatch: ["#e0663a", "#334155"] },
  { value: "brutalist", label: "Brutalist", swatch: ["#ef4444", "#000000"] },
] as const;
export type Preset = (typeof PRESETS)[number]["value"];

interface ThemeCtx {
  mode: Mode;
  preset: Preset;
  isDark: boolean;
  setMode: (m: Mode) => void;
  setPreset: (p: Preset) => void;
}

const Ctx = createContext<ThemeCtx | null>(null);
const KEY = "audit-theme";

function read(): { mode: Mode; preset: Preset } {
  try {
    const t = JSON.parse(localStorage.getItem(KEY) || "{}");
    return { mode: (["light", "dark", "system"].includes(t.mode) ? t.mode : "system") as Mode, preset: (PRESETS.some((p) => p.value === t.preset) ? t.preset : "audit") as Preset };
  } catch {
    return { mode: "system", preset: "audit" };
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState(read);
  const [systemDark, setSystemDark] = useState(() => matchMedia("(prefers-color-scheme: dark)").matches);

  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  const isDark = state.mode === "dark" || (state.mode === "system" && systemDark);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
    document.documentElement.dataset.themePreset = state.preset;
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* sin almacenamiento: no pasa nada */ }
  }, [isDark, state]);

  const setMode = useCallback((mode: Mode) => setState((s) => ({ ...s, mode })), []);
  const setPreset = useCallback((preset: Preset) => setState((s) => ({ ...s, preset })), []);
  const value = useMemo(() => ({ ...state, isDark, setMode, setPreset }), [state, isDark, setMode, setPreset]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTheme fuera de ThemeProvider");
  return v;
}
