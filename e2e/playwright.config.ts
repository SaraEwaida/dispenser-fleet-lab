import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests against a running stack: FastAPI serving the built console on :8100 with the simulator on.
 * The fleet runs at 30x, so one fleet minute is two real seconds. Tests that wait for alerts allow for that.
 * Test titles carry the manual test case code (e.g. [TC-040]).
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1, // faults are fleet-wide state; run serially
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["json", { outputFile: "results/results.json" }], ["html", { outputFolder: "results/html", open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "desktop-chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
