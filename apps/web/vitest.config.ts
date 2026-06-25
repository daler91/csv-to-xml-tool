import { defineConfig } from "vitest/config";
import path from "node:path";

// Server route + lib unit tests (QUAL-1). `node` environment — these exercise
// API route handlers and queue libs, not React components. The `@` alias mirrors
// tsconfig's paths so tests import the same module specifiers as app code.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
});
