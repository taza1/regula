const { test, expect } = require("@playwright/test");

const baseURL = process.env.RESEARCH_BASE_URL || "http://127.0.0.1:8010";

test("dashboard completes a local research journey", async ({ page }) => {
  await page.goto(`${baseURL}/dashboard`);
  await expect(page.getByText("Offline planner · no model charges")).toBeVisible();

  await page.getByRole("button", { name: "+ New project" }).click();
  await page.getByLabel("Project name").fill(`Browser project ${Date.now()}`);
  await page.getByLabel("Description").fill("Dashboard browser verification");
  await page.getByRole("dialog").getByRole("button", { name: "Create project" }).click();

  await page.getByRole("button", { name: "+ New research" }).click();
  await page.getByLabel("Title").fill("Local dashboard verification");
  await page.getByLabel("Research question").fill("What evidence supports local research execution?");
  await page.getByLabel("Scope").fill("Use the deterministic local provider and inspect the generated result.");
  await page.getByRole("dialog").getByRole("button", { name: "Create research run" }).click();

  await page.getByRole("button", { name: "Generate plan" }).click();
  await expect(page.locator("#plan-content")).toContainText("Search queries");
  await page.getByRole("button", { name: "Confirm scope & start research" }).click();

  await expect(page.locator("#state")).toHaveText(/reviewing|insufficient evidence/i, { timeout: 30_000 });
  await expect(page.locator("#draft")).not.toContainText("The draft appears after evidence collection.");
  await expect(page.locator("#evidence-count")).toContainText("shown");
  await expect(page.locator("#job-message")).toContainText("Draft ready", { timeout: 30_000 });
});
