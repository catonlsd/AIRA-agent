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
      }
    }
  },
  plugins: []
};

export default config;
