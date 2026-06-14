import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // sivra design tokens — calm, editorial, warm
        paper: "#F4F2EB",
        ink: "#211f1a",
        accent: "#3A357C",
      },
      fontFamily: {
        // wired to next/font CSS variables in src/app/layout.tsx
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "-apple-system", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
