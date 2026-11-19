import coreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const eslintConfig = [
  ...coreWebVitals,
  ...nextTypescript,
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { varsIgnorePattern: "^_", argsIgnorePattern: "^_" },
      ],
      // react-hooks v7 (via eslint-config-next 16) added these rules; the
      // existing effect-based data fetching predates them. Warnings only so
      // the upgrade does not force a rewrite of fetching hooks.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/incompatible-library": "warn",
      "react-hooks/static-components": "warn",
    },
  },
];

export default eslintConfig;
