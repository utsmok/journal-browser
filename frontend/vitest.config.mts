import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // tsconfig.json sets jsx: preserve for Next; the oxc transform needs the
  // automatic runtime to compile TSX (app files included) under test.
  oxc: {
    jsx: {
      runtime: "automatic",
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
  },
});
