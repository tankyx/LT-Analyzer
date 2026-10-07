// Plain module (no 'use client') so the server-rendered layout can inline the
// key into its pre-paint script. Importing from ThemeContext.tsx would hand the
// server a client-reference stub instead of the string.
export type Theme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'lt-theme';

/**
 * Pick the theme for first render: an explicit saved choice wins, otherwise
 * the pit wall defaults to dark (the live-timing scene is low-light).
 * Mirrored by the inline boot script in layout.tsx.
 */
export function resolveInitialTheme(stored: string | null | undefined): Theme {
  if (stored === 'dark' || stored === 'light') return stored;
  return 'dark';
}
