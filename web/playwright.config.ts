import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "test/browser",
  timeout: 60_000,
  workers: 1,
  fullyParallel: false,
  reporter: "line",
  outputDir: "test-results"
});
