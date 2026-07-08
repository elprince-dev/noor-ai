import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "serif"],
      },
      colors: {
        // Deep ink / near-black background scale
        ink: {
          950: "#04060D",
          900: "#070B16",
          800: "#0B1120",
          700: "#111A2E",
          600: "#18233D",
          500: "#22304F",
        },
        // Golden — the signature "Noor" (light) accent
        gold: {
          50: "#FCF7E6",
          100: "#F9ECBF",
          200: "#F2DA84",
          300: "#EBC84E",
          400: "#E6B92A",
          500: "#D19E12",
          600: "#AE7E08",
          700: "#8A6206",
        },
        // Royal blue — interactive / secondary
        royal: {
          300: "#7EA6FF",
          400: "#5B8DEF",
          500: "#2F6BFF",
          600: "#1D4ED8",
          700: "#1E3A8A",
        },
        // Crimson — errors / destructive only
        crimson: {
          400: "#F4696B",
          500: "#E23D3D",
          600: "#C42B2B",
        },
      },
      boxShadow: {
        gold: "0 0 0 1px rgba(230,185,42,0.25), 0 8px 40px -8px rgba(230,185,42,0.45)",
        "gold-sm": "0 4px 20px -6px rgba(230,185,42,0.4)",
        glass:
          "0 8px 32px -4px rgba(0,0,0,0.5), inset 0 1px 0 0 rgba(255,255,255,0.06)",
        glow: "0 0 60px -12px rgba(47,107,255,0.5)",
      },
      backgroundImage: {
        "gold-gradient":
          "linear-gradient(135deg, #F2DA84 0%, #E6B92A 45%, #AE7E08 100%)",
        "gold-sheen":
          "linear-gradient(135deg, #FCF7E6 0%, #EBC84E 40%, #D19E12 70%, #8A6206 100%)",
        "royal-gradient":
          "linear-gradient(135deg, #5B8DEF 0%, #2F6BFF 50%, #1E3A8A 100%)",
        "ink-radial":
          "radial-gradient(1200px 600px at 50% -10%, rgba(47,107,255,0.18), transparent 60%), radial-gradient(900px 500px at 90% 10%, rgba(230,185,42,0.12), transparent 55%), radial-gradient(700px 500px at 0% 90%, rgba(226,61,61,0.08), transparent 55%)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        float: {
          "0%,100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-10px)" },
        },
        "aurora-shift": {
          "0%,100%": { transform: "translate(0,0) scale(1)" },
          "50%": { transform: "translate(-4%,3%) scale(1.08)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        bounceDot: {
          "0%,80%,100%": { transform: "translateY(0)", opacity: "0.4" },
          "40%": { transform: "translateY(-6px)", opacity: "1" },
        },
        "glow-pulse": {
          "0%,100%": { opacity: "0.55" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.5s cubic-bezier(0.22,1,0.36,1) both",
        "fade-in": "fade-in 0.6s ease both",
        float: "float 6s ease-in-out infinite",
        aurora: "aurora-shift 18s ease-in-out infinite",
        shimmer: "shimmer 2.5s linear infinite",
        "bounce-dot": "bounceDot 1.4s ease-in-out infinite",
        "glow-pulse": "glow-pulse 3s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;