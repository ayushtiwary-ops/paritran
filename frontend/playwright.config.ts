import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the demo-mode e2e (SPEC 14, SPEC 16).
 *
 * The test drives the live web app through a Vite dev server. Vite proxies
 * /api and /health to VITE_PROXY_TARGET (a uvicorn running the edited
 * backend so the /api/demo/* endpoints exist); the config only owns the
 * Vite server, the backend is brought up out of band by the run driver.
 *
 * baseURL and the Vite port default to 5173 and can be overridden with
 * E2E_BASE_URL / E2E_WEB_PORT. No secret is stored here: the supervisor
 * password is read from the environment at run time (never committed).
 */

const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? "5173");
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${WEB_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  // The demo narrates for ~35 s at scale 1.0; give the whole test headroom
  // over the SPEC 14 ninety-second ceiling plus login and asserts.
  timeout: 150_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: `npm run dev -- --port ${WEB_PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    env: {
      VITE_PROXY_TARGET:
        process.env.VITE_PROXY_TARGET ?? "http://localhost:8099",
    },
  },
});
