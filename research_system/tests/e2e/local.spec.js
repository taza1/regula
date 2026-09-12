const { test, expect } = require("@playwright/test");

const baseURL = process.env.RESEARCH_BASE_URL || "http://127.0.0.1:8010";
const expectedProvider = process.env.EXPECTED_MODEL_PROVIDER || "mock";

test("Swagger renders the updated local API", async ({ page }) => {
  const response = await page.goto(`${baseURL}/docs`);
  expect(response.ok()).toBeTruthy();
  await expect(page.getByText("Multi-Agent Research System API")).toBeVisible();
  await expect(page.getByText("/api/v1/ai/status", { exact: true })).toBeVisible();
});

test("project, run, evidence, and draft work end to end", async ({ request }) => {
  const tenantId = `TEN-PW-${Date.now()}`;
  const headers = { "X-Tenant-Id": tenantId, "X-User-Id": "playwright-user" };
  const created = await request.post(
    `${baseURL}/api/v1/projects`,
    {
      headers,
      data: { name: "Playwright research", description: "Local smoke test" },
    },
  );
  expect(created.ok()).toBeTruthy();
  const projectId = (await created.json()).project.project_id;

  const runResponse = await request.post(
    `${baseURL}/api/v1/projects/${projectId}/runs`,
    {
      headers,
      data: {
        title: "Evidence quality",
        primary_question: "How should evidence quality be assessed?",
        scope_description: "Academic evidence only",
      },
    },
  );
  expect(runResponse.ok()).toBeTruthy();
  const runId = (await runResponse.json()).run.run_id;

  const planResponse = await request.post(
    `${baseURL}/api/v1/projects/${projectId}/runs/${runId}/plan`,
    { headers },
  );
  expect(planResponse.ok()).toBeTruthy();
  const plan = await planResponse.json();
  expect(plan.provider.provider).toBe("mock");
  expect(plan.plan.subquestions.length).toBeGreaterThan(0);

  const confirmResponse = await request.post(
    `${baseURL}/api/v1/projects/${projectId}/runs/${runId}/confirm-scope`,
    { headers, data: { confirmed: true } },
  );
  expect(confirmResponse.ok()).toBeTruthy();

  const execution = await request.post(
    `${baseURL}/api/v1/projects/${projectId}/runs/${runId}/execute-local`,
    { headers },
  );
  expect(execution.ok()).toBeTruthy();
  const executionBody = await execution.json();
  expect(executionBody.evidence_count).toBeGreaterThan(0);
  expect(executionBody.provider_outcomes[0].status).toBe("success");

  const synthesis = await request.post(
    `${baseURL}/api/v1/projects/${projectId}/runs/${runId}/synthesize-local`,
    { headers },
  );
  expect(synthesis.ok()).toBeTruthy();
  const synthesisBody = await synthesis.json();
  expect(synthesisBody.claims.length).toBeGreaterThan(0);
  expect(synthesisBody.draft.references.length).toBeGreaterThan(0);

  const validation = await request.post(
    `${baseURL}/api/v1/projects/${projectId}/runs/${runId}/validate-citations-local`,
    { headers },
  );
  expect(validation.ok()).toBeTruthy();
  const validationBody = await validation.json();
  expect(validationBody.passed).toBeTruthy();
  expect(validationBody.validated_claim_ids.length).toBeGreaterThan(0);

  const retrieved = await request.get(
    `${baseURL}/api/v1/projects/${projectId}/runs/${runId}`,
    { headers },
  );
  expect(retrieved.ok()).toBeTruthy();
  expect((await retrieved.json()).state).toBe("reviewing");
});

test("model-provider status is explicit", async ({ request }) => {
  const response = await request.get(`${baseURL}/api/v1/ai/status`);
  expect(response.ok()).toBeTruthy();
  const status = await response.json();
  expect(status.provider).toBe(expectedProvider);
  expect(status.configured).toBeTruthy();
  expect(status.model).toBeTruthy();
});
