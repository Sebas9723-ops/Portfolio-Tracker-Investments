import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./node_modules/@tremor/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bloomberg: {
          bg:         "rgb(var(--tw-bg) / <alpha-value>)",
          card:       "rgb(var(--tw-card) / <alpha-value>)",
          border:     "rgb(var(--tw-border) / <alpha-value>)",
          gold:       "rgb(var(--tw-gold) / <alpha-value>)",
          "gold-dim": "rgb(var(--tw-gold-dim) / <alpha-value>)",
          green:      "rgb(var(--tw-green) / <alpha-value>)",
          red:        "rgb(var(--tw-red) / <alpha-value>)",
          muted:      "rgb(var(--tw-muted) / <alpha-value>)",
          text:       "rgb(var(--tw-text) / <alpha-value>)",
          "text-dim": "rgb(var(--tw-text-dim) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["Inter", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "8px",
      },
      boxShadow: {
        card: "0 1px 3px 0 rgba(0,0,0,0.07), 0 1px 2px -1px rgba(0,0,0,0.05)",
      },
    },
  },
  plugins: [],
};

export default config;
