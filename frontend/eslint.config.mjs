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
      // react-hooks v7 (via eslint-config-next 16) added these rules.
      // set-state-in-effect: every site is mount-time hydration from
      // sessionStorage/localStorage (guarded so server and client render
      // match) or a deliberate prop-change reset; the sanctioned
      // useSyncExternalStore rewrite is deferred until after the demo.
      "react-hooks/set-state-in-effect": "off",
      // incompatible-library: TanStack Table's useReactTable intentionally
      // returns non-memoizable getters; the compiler skips the component,
      // and the search table is the only call site. refs and
      // static-components had no remaining sites, so their defaults apply.
      "react-hooks/incompatible-library": "off",
    },
  },
];

export default eslintConfig;
