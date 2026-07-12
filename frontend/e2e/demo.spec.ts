/**
 * Demo-mode end-to-end (SPEC 14, SPEC 16 Playwright row).
 *
 * Drives the live web app through Vite (which proxies /api to a uvicorn
 * running the edited backend). It signs in as the seeded supervisor, runs
 * the guided demo, and asserts the whole narrative:
 *
 *  - the nine pipeline stages all start and complete (stage rail),
 *  - all five paced beats are reached,
 *  - the planted fabrication is blocked live by the F9 gate (WITHHELD),
 *  - the tamper test breaks the scratch chain,
 *  - the run completes in under ninety seconds,
 *  - and the browser console stays clean (zero errors).
 *
 * The supervisor password is read from the environment at run time
 * (injected from .env by the run driver); it is never committed here.
 */

import { expect, test, type ConsoleMessage } from "@playwright/test";

const SUPERVISOR_USER = process.env.DEMO_SUPERVISOR_USER ?? "supervisor1";
const SUPERVISOR_PASSWORD = process.env.SUPERVISOR1_PASSWORD ?? "";
const NINETY_SECONDS = 90_000;
const SHOT_DIR = process.env.E2E_SHOT_DIR ?? "test-results/demo-shots";

test("guided demo runs the full narrative under 90s with zero console errors", async ({
  page,
}) => {
  expect(
    SUPERVISOR_PASSWORD,
    "SUPERVISOR1_PASSWORD must be injected from .env at run time",
  ).not.toEqual("");

  // Collect every browser console error and uncaught page error.
  const consoleErrors: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));

  // --- sign in as the seeded supervisor -----------------------------------
  await page.goto("/login");
  await page.fill("#login-username", SUPERVISOR_USER);
  await page.fill("#login-password", SUPERVISOR_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  // Wait for the authenticated shell (the logout control only renders once
  // signed in) so the session token is stored before we navigate.
  await expect(page.getByRole("button", { name: "logout" })).toBeVisible();

  // Reaching Demo with the Start button visible proves auth succeeded
  // (RequireAuth would otherwise bounce back to /login).
  await page.goto("/demo");
  await expect(page.getByTestId("demo-start")).toBeVisible();

  // --- start the demo and time it -----------------------------------------
  const startedAt = Date.now();
  await page.getByTestId("demo-start").click();

  // Nine stage.started events => nine stage pills, all reaching done.
  await expect(page.locator(".stage-rail .stage-pill")).toHaveCount(9);
  await expect(page.locator(".stage-rail .stage-pill.done")).toHaveCount(9, {
    timeout: 60_000,
  });

  // Beat 2: the graph is collapsing and the counters are up. Capture the
  // mid-run screenshot here.
  await expect(page.getByTestId("beat-2")).toHaveAttribute(
    "data-active",
    "true",
    { timeout: NINETY_SECONDS },
  );
  await page.screenshot({ path: `${SHOT_DIR}/demo-midrun.png`, fullPage: true });

  // Five paced beats reached.
  for (let i = 1; i <= 5; i++) {
    await expect(page.getByTestId(`beat-${i}`)).toHaveAttribute(
      "data-active",
      "true",
      { timeout: NINETY_SECONDS },
    );
  }

  // The planted fabrication is blocked live by the F9 gate (beat 4).
  const blocked = page.getByTestId("planted-blocked").first();
  await expect(blocked).toBeVisible({ timeout: NINETY_SECONDS });
  await expect(blocked).toContainText("WITHHELD");
  await blocked.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: `${SHOT_DIR}/demo-blocked-fabrication.png`,
    fullPage: true,
  });

  // The tamper test breaks the scratch chain (beat 5).
  await expect(page.getByTestId("tamper-result")).toHaveAttribute(
    "data-broke",
    "true",
    { timeout: NINETY_SECONDS },
  );

  // The demo completes, and it does so under ninety seconds.
  await expect(page.getByTestId("demo-status")).toHaveAttribute(
    "data-status",
    "completed",
    { timeout: 100_000 },
  );
  const elapsedMs = Date.now() - startedAt;
  const statusText = (await page.getByTestId("demo-status").textContent()) ?? "";
  // eslint-disable-next-line no-console
  console.log(
    `[demo] start-to-complete ${(elapsedMs / 1000).toFixed(1)} s (< 90 s); status line: "${statusText.trim()}"`,
  );
  expect(
    elapsedMs,
    `demo should complete under 90s (took ${elapsedMs} ms)`,
  ).toBeLessThan(NINETY_SECONDS);

  // The manual "Plant a fabrication" control also blocks a claim live.
  await page.getByRole("button", { name: "Plant a fabrication" }).click();
  await expect(page.getByTestId("planted-blocked").last()).toBeVisible();

  // The console stayed clean throughout.
  expect(
    consoleErrors,
    `expected zero console errors, saw: ${JSON.stringify(consoleErrors)}`,
  ).toHaveLength(0);
});
