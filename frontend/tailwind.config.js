import animate from "tailwindcss-animate";

// Colores como canales oklch («L C H») para poder usar transparencias: bg-primary/50
const c = (v) => `oklch(var(--${v}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: c("background"),
        foreground: c("foreground"),
        card: { DEFAULT: c("card"), foreground: c("card-foreground") },
        popover: { DEFAULT: c("popover"), foreground: c("popover-foreground") },
        primary: { DEFAULT: c("primary"), foreground: c("primary-foreground") },
        secondary: { DEFAULT: c("secondary"), foreground: c("secondary-foreground") },
        muted: { DEFAULT: c("muted"), foreground: c("muted-foreground") },
        accent: { DEFAULT: c("accent"), foreground: c("accent-foreground") },
        destructive: { DEFAULT: c("destructive"), foreground: "oklch(0.985 0 0)" },
        brand: { DEFAULT: c("brand"), foreground: c("brand-foreground") },
        border: "oklch(var(--border) / var(--border-a))",
        input: "oklch(var(--input) / var(--input-a))",
        ring: c("ring"),
        chart: { 1: c("chart-1"), 2: c("chart-2"), 3: c("chart-3"), 4: c("chart-4"), 5: c("chart-5") },
        sidebar: {
          DEFAULT: c("sidebar"),
          foreground: c("sidebar-foreground"),
          primary: c("sidebar-primary"),
          "primary-foreground": c("sidebar-primary-foreground"),
          accent: c("sidebar-accent"),
          "accent-foreground": c("sidebar-accent-foreground"),
          border: "oklch(var(--sidebar-border) / var(--sidebar-border-a))",
          ring: c("sidebar-ring"),
        },
        // misma paleta que el informe Word
        severity: { critical: "#7B1020", high: "#C2410C", medium: "#A16207", low: "#2F7D32", none: "#6B7280" },
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)", xl: "calc(var(--radius) + 4px)" },
      fontFamily: { sans: ["var(--font-sans)"], mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"] },
    },
  },
  plugins: [animate],
};
