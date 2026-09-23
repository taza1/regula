const { test, expect } = require("@playwright/test");

const enabled = process.env.RUN_LIVE_RESEARCH_E2E === "1";
const baseURL = process.env.RESEARCH_BASE_URL || "http://127.0.0.1:8015";
const expectedProvider = process.env.EXPECTED_MODEL_PROVIDER || "azure";

test("live scholarly sources and Azure or Foundry model complete a guarded research run", async ({ page, request }, testInfo) => {
  test.skip(!enabled, "Set RUN_LIVE_RESEARCH_E2E=1 to incur live provider/model usage.");
  test.setTimeout(12 * 60 * 1000);

  const tenant = `TEN-LIVE-${Date.now()}`;
  const headers = { "X-Tenant-Id": tenant, "X-User-Id": "live-smoke-reviewer" };

  const dashboard = await page.goto(`${baseURL}/dashboard`);
  expect(dashboard.ok()).toBeTruthy();
  await expect(page.locator("#provider")).toContainText(new RegExp(expectedProvider, "i"));

  const providerResponse = await request.get(`${baseURL}/api/v1/ai/status`);
  expect(providerResponse.ok()).toBeTruthy();
  const provider = await providerResponse.json();
  expect(provider.provider).toBe(expectedProvider);
  expect(provider.remote).toBeTruthy();

  const infoResponse = await request.get(`${baseURL}/api/v1/system/info`);
  expect(infoResponse.ok()).toBeTruthy();
  const info = await infoResponse.json();
  expect(info.source_connector).toBe("scholarly");

  const projectResponse = await request.post(`${baseURL}/api/v1/projects`, {
    headers,
    data: { name: "Live integration smoke", description: "Disposable source/model verification" },
  });
  expect(projectResponse.ok()).toBeTruthy();
  const projectId = (await projectResponse.json()).project.project_id;

  const runResponse = await request.post(`${baseURL}/api/v1/projects/${projectId}/runs`, {
    headers,
    data: {
      title: "RAG factual accuracy evidence",
      primary_question: "What empirical evidence shows when retrieval augmented generation improves or worsens factual accuracy?",
      scope_description: "Scholarly work from 2023 through 2026, including negative and null findings.",
      date_range_start: "2023-01-01",
      date_range_end: "2026-12-31",
      max_sources: 9,
    },
  });
  expect(runResponse.ok()).toBeTruthy();
  const runId = (await runResponse.json()).run.run_id;
  const runURL = `${baseURL}/api/v1/projects/${projectId}/runs/${runId}`;

  expect((await request.post(`${runURL}/plan`, { headers })).ok()).toBeTruthy();
  expect((await request.post(`${runURL}/confirm-scope`, { headers, data: { confirmed: true } })).ok()).toBeTruthy();
  const execution = await request.post(`${runURL}/execute`, { headers, data: { full_text: false } });
  expect(execution.status()).toBe(202);

  let results;
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const response = await request.get(`${runURL}/results`, { headers });
    expect(response.ok()).toBeTruthy();
    results = await response.json();
    if (["awaiting_approval", "adjudication_required", "failed", "insufficient_evidence"].includes(results.run.state)) break;
    await page.waitForTimeout(3000);
  }

  expect(results).toBeTruthy();
  expect(["awaiting_approval", "adjudication_required"]).toContain(results.run.state);
  expect(results.execution.status).toBe("completed");
  expect(results.evidence.length).toBeGreaterThan(0);
  expect(results.model_review).toBeTruthy();
  expect(results.model_review.provider).toBe(expectedProvider);
  const providers = new Set(results.execution.provider_outcomes.map(item => item.provider));
  expect(providers.has("openalex")).toBeTruthy();
  expect(providers.has("crossref")).toBeTruthy();
  expect(providers.has("arxiv")).toBeTruthy();
  expect(results.evidence.every(item => !item.url.startsWith("local://"))).toBeTruthy();

  await testInfo.attach("live-research-result", {
    body: Buffer.from(JSON.stringify({ projectId, runId, provider, info, results }, null, 2)),
    contentType: "application/json",
  });
});
