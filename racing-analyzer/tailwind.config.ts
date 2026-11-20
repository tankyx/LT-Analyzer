import type { Config } from "tailwindcss";

// Design tokens live as RGB triplets in globals.css (`:root` = light, `.dark`
// = dark) so every utility below works with Tailwind's `/opacity` modifier
// and flips theme without a single `dark:` variant in component code.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: "class",
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // pit-wall palette
        canvas: token("c-canvas"),
        surface: token("c-surface"),
        "surface-2": token("c-surface-2"),
        line: token("c-line"),
        "line-strong": token("c-line-strong"),
        ink: token("c-ink"),
        muted: token("c-muted"),
        accent: token("c-accent"),
        "accent-hi": token("c-accent-hi"),
        "accent-ink": token("c-accent-ink"),
        live: token("c-live"),
        alarm: token("c-alarm"),
        info: token("c-info"),
        "on-signal": token("c-on-signal"),
        class1: token("c-class1"),
        class2: token("c-class2"),
        focus: token("c-focus"),
        best: token("c-best"),
        // backdrop behind sheets, drawers and dialogs (alpha is part of the token)
        scrim: "rgb(0 0 0 / 0.6)",
        // data palette: stints, chart series, pit lanes
        ...Object.fromEntries(
          Array.from({ length: 10 }, (_, i) => [`series-${i + 1}`, token(`c-series-${i + 1}`)]),
        ),
      },
      fontFamily: {
        sans: ["var(--font-sans)", "Helvetica Neue", "Arial", "sans-serif"],
        cond: ["var(--font-cond)", "Arial Narrow", "Arial", "sans-serif"],
        mono: ["var(--font-mono)", "SF Mono", "Menlo", "Consolas", "monospace"],
      },
      // Two steps below `text-xs` for dense timing rows; no arbitrary
      // `text-[Npx]` sizes in components.
      fontSize: {
        "3xs": "10px",
        "2xs": "11px",
      },
      // Tints on tokens come in three steps: /8 (row wash), /15 (pill and
      // chip grounds), /25 (hover on a tint).
      opacity: {
        8: "0.08",
      },
      // The one shadow, for layers that float: menus, toasts, sheets.
      boxShadow: {
        overlay: "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
      },
    },
  },
  plugins: [],
} satisfies Config;
