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
        // legacy aliases still referenced by a few older components
        background: "var(--background)",
        foreground: "var(--foreground)",
        // pit-wall palette
        canvas: token("c-canvas"),
        surface: token("c-surface"),
        "surface-2": token("c-surface-2"),
        line: token("c-line"),
        ink: token("c-ink"),
        muted: token("c-muted"),
        accent: token("c-accent"),
        "accent-ink": token("c-accent-ink"),
        live: token("c-live"),
        alarm: token("c-alarm"),
        info: token("c-info"),
        class1: token("c-class1"),
        class2: token("c-class2"),
      },
      fontFamily: {
        sans: ["var(--font-sans)", "Helvetica Neue", "Arial", "sans-serif"],
        cond: ["var(--font-cond)", "Arial Narrow", "Arial", "sans-serif"],
        mono: ["var(--font-mono)", "SF Mono", "Menlo", "Consolas", "monospace"],
      },
      keyframes: {
        "live-blink": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        "live-blink": "live-blink 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
