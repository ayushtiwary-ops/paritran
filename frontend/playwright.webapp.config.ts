import { defineConfig, devices } from "@playwright/test";

// Dedicated Playwright config for the hosted /app/ parity gate (SPEC_HOSTED_APP
// A4/A5). It serves the built docs/app via `vite preview` at the production base
// (/paritran/app/) and drives a headless Chromium. It is separate from the
// demo-mode e2e (playwright.config.ts) so neither picks up the other's specs
// and the parity gate needs no backend.
const PORT = Number(process.env.WEBAPP_PORT ?? "4188");
const BASE = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e-webapp",
  timeout: 180_000,
  expect: { timeout: 130_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: BASE,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npx vite preview -c vite.replay.config.ts --port ${PORT} --strictPort`,
    url: `${BASE}/paritran/app/`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
