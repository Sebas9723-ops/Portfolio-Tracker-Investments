import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bloomberg: {
          bg: "#0b0f14",
          card: "#111820",
          border: "#1e2535",
          gold: "#f3a712",
          "gold-dim": "#b87e0e",
          green: "#4dff4d",
          red: "#ff4d4d",
          muted: "#8a9bb5",
          text: "#d4dde8",
          "text-dim": "#5a6a80",
        },
      },
      fontFamily: {
        mono: ["IBM Plex Mono", "Courier New", "monospace"],
        sans: ["IBM Plex Mono", "monospace"],
      },
      borderRadius: {
        DEFAULT: "2px",
      },
    },
  },
  plugins: [],
};

export default config;
