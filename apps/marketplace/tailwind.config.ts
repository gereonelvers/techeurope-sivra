import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
      },
    },
  },
  // Skin classes are applied dynamically via the [site] route param, so we
  // safelist the accent utilities the theme map references.
  safelist: [
    { pattern: /^(bg|text|border|ring|from|to|hover:bg|hover:text|focus:ring)-(slate|zinc|gray|stone|blue|sky|indigo|violet|fuchsia|pink|rose|emerald|amber)-(50|100|200|300|400|500|600|700|800|900)$/ },
  ],
  plugins: [],
};

export default config;
