'use client';

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

import { THEME_STORAGE_KEY, resolveInitialTheme, type Theme } from './themeKey';

export { THEME_STORAGE_KEY, resolveInitialTheme };
export type { Theme };

interface ThemeContextValue {
  theme: Theme;
  isDark: boolean;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'light',
  isDark: false,
  setTheme: () => {},
  toggleTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Server and first client render agree on 'light'; the effect below then
  // adopts the saved/OS theme. The <html> class itself is already correct by
  // then (set by the inline script), so there is no visible flash.
  const [theme, setThemeState] = useState<Theme>('light');

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    } catch {
      /* storage blocked */
    }
    const prefersDark =
      typeof window.matchMedia === 'function' &&
      !!window.matchMedia('(prefers-color-scheme: dark)').matches;
    setThemeState(resolveInitialTheme(stored, prefersDark));
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle('dark', theme === 'dark');
    root.style.colorScheme = theme;
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* storage blocked */
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  }, [theme, setTheme]);

  return (
    <ThemeContext.Provider value={{ theme, isDark: theme === 'dark', setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
