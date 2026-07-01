import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#172026",
        panel: "#f8faf7",
        line: "#dbeafe",
        accent: "#2563eb",
        amber: "#b66a12",
      },
      fontWeight: {
        'black': 'var(--weight-heading)',
      },
      fontSize: {
        '11': ['var(--type-caption)', { lineHeight: 'var(--leading-caption)' }],
      },
      spacing: {
        '1':   'var(--space-1)',    /*  4px */
        '1.5': 'var(--space-1-5)', /*  6px */
        '2':   'var(--space-2)',    /*  8px */
        '2.5': 'var(--space-2-5)', /* 10px */
        '3':   'var(--space-3)',    /* 12px */
        '4':   'var(--space-4)',    /* 16px */
        '5':   'var(--space-5)',    /* 20px */
        '6':   'var(--space-6)',    /* 24px */
        '8':   'var(--space-8)',    /* 32px */
        '10':  'var(--space-10)',   /* 40px */
      },
    }
  },
  plugins: []
};

export default config;
