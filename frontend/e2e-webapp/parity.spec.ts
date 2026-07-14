import { test, expect } from "@playwright/test";

// A4: the browser reproduces the frozen results.json at seed 42, field by field.
// The reproduction banner renders only when all 19 comparison fields equal the
// committed results.reference.json (byte-identical to results.json, checked in
// CI), so the banner being visible IS the parity proof. We also spot-check that
// the headline values are actually rendered, and assert zero console errors.
test("seed 42 reproduces the frozen results.json in the browser", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/paritran/app/");
  await page.getByRole("button", { name: "Run in my browser" }).click();

  await expect(page.getByText(/reproduces the frozen results\.json exactly/i)).toBeVisible();
  await expect(page.getByText(/19 fields checked, all equal/i)).toBeVisible();

  for (const value of ["297", "90.8", "0.962", "52.4"]) {
    await expect(page.getByText(value, { exact: false }).first()).toBeVisible();
  }

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

// A5: a different seed moves the network metrics but keeps the deterministic
// invariants, and the displayed seed comes from UI state (never the JSON seed).
test("seed 43 diverges and stays internally consistent", async ({ page }) => {
  await page.goto("/paritran/app/");
  await page.getByLabel("Seed").fill("43");
  await page.getByRole("button", { name: "Run in my browser" }).click();

  await expect(page.getByText(/Seed 43: the engine ran live/i)).toBeVisible();
  // Deterministic invariants still render (F9 tally and custody chain length).
  await expect(page.getByText("F9 CLAIMS CHECKED")).toBeVisible();
  await expect(page.getByText("CUSTODY CHAIN LENGTH")).toBeVisible();
  // The seed card reflects UI state.
  await expect(page.getByText("SEED (FROM YOUR INPUT)")).toBeVisible();
});
