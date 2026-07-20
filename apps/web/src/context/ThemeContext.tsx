import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Theme } from "@radix-ui/themes";

type ThemeMode = "light" | "dark";

interface ThemeContextValue {
  mode: ThemeMode;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);
const THEME_KEY = "qingwan.theme";

function initialTheme(): ThemeMode {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    document.documentElement.style.colorScheme = mode;
    localStorage.setItem(THEME_KEY, mode);
  }, [mode]);

  const value = useMemo(
    () => ({ mode, toggle: () => setMode((current) => (current === "light" ? "dark" : "light")) }),
    [mode],
  );

  return (
    <ThemeContext.Provider value={value}>
      <Theme appearance={mode} accentColor="jade" grayColor="slate" radius="large" scaling="100%">
        {children}
      </Theme>
    </ThemeContext.Provider>
  );
}

export function useThemeMode() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useThemeMode 必须在 ThemeProvider 内使用");
  return value;
}
