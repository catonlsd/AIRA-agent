// Flat ESLint config for Next.js 16 + ESLint 9.
// `next lint` was removed in Next 16; lint runs via the ESLint CLI (`eslint .`).
// eslint-config-next v16 ships a native flat-config array, so we spread it.
import next from "eslint-config-next";

const eslintConfig = [
  // Global ignores (build output, deps, generated files).
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "next-env.d.ts",
      "*.config.js",
      "*.config.mjs",
      "**/*.tsbuildinfo",
      // Node-runnable presenter tests (run via `npm test`, not linted/built).
      "**/*.test.mts",
    ],
  },
  ...next,
  {
    rules: {
      // New aggressive rule in react-hooks 6 (bundled with Next 16). The repo's
      // existing hydration-flag and effect-based data-fetch patterns trip it.
      // These are advisory (perf), not correctness bugs, so keep them visible as
      // warnings rather than blocking the build. Tracked as tech debt.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];

export default eslintConfig;
