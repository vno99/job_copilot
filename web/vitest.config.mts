import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Configuration Vitest — alignée sur le guide officiel Next.js 16
// (node_modules/next/dist/docs/01-app/02-guides/testing/vitest.md).
// L'alias "@/*" de tsconfig.json est résolu nativement par Vite
// (resolve.tsconfigPaths, recommandé à la place de vite-tsconfig-paths).
export default defineConfig({
  plugins: [react()],
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    // DOM simulé (tests de composants) — pas de navigateur réel.
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
