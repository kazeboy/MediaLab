import { useCallback, useEffect, useState } from "react";

/**
 * Colour theme. Dark is the default for everyone; the OS/browser appearance is ignored on purpose.
 * The choice is stored in localStorage and applied as <html data-theme="…">.
 *
 * The same rules run once before React, in the inline script in `index.html` (no flash of the wrong
 * theme). Keep THEME_KEY, the default and THEME_COLOR in sync with that script.
 */
export type Theme = "dark" | "light";
export const THEME_KEY = "medialab.theme";
export const DEFAULT_THEME: Theme = "dark";
export const THEME_COLOR: Record<Theme, string> = { dark: "#0b0d10", light: "#f4f5f7" };

export function readSavedTheme(): Theme | null {
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null; // storage blocked (private mode, policies): fall back to the default
  }
}

/** The theme currently on the page (set by the inline script, or by `applyTheme`). */
export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : DEFAULT_THEME;
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme]);
}

export function saveTheme(theme: Theme) {
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* not persisted, but still applied for this page */
  }
}

/** Current theme plus a toggle that applies and remembers the choice; follows changes from other tabs. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => readSavedTheme() ?? currentTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === THEME_KEY && (e.newValue === "light" || e.newValue === "dark")) setTheme(e.newValue);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const toggle = useCallback(() => {
    setTheme((t) => {
      const next: Theme = t === "dark" ? "light" : "dark";
      saveTheme(next);
      return next;
    });
  }, []);

  return { theme, toggle };
}
