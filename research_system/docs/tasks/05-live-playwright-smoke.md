# Task 05: Operationalize the live Playwright smoke test

Priority: P0

Related work: TASK-024, TASK-026, TASK-028, TASK-029

Status: Test and run guide present; repeatable evidence pending

## Outcome

A documented browser test proves that a local Regula application can retrieve real scholarly evidence, use the selected remote model path, synthesize and review a report, and stop in a safe gated state without mock sources or model responses.

## Required journey

1. Start the local API with `SOURCE_CONNECTOR=scholarly` and the selected remote model provider.
2. Open the dashboard and create a disposable project and research run.
3. Submit and confirm a narrow research question.
4. Retrieve OpenAlex, Crossref and arXiv provider outcomes.
5. Inspect non-synthetic evidence and provenance.
6. Run synthesis, semantic fact-checking and critical review.
7. Verify the run finishes at `awaiting_approval` or the safe `adjudication_required` state.
8. Do not approve or release the report during the smoke test.

## Implementation checklist

- [ ] Keep the live test opt-in and excluded from untrusted pull-request execution.
- [ ] Validate the reported model provider matches `EXPECTED_MODEL_PROVIDER`.
- [ ] Fail on synthetic sources, placeholder evidence or a mock model provider.
- [ ] Check provider outcomes, evidence hashes, claim citations and review findings.
- [ ] Add bounded timeouts and diagnostics for provider/model failures.
- [ ] Save Playwright trace/video/screenshots and redacted JSON result.
- [ ] Create a protected manual workflow with spending and timeout limits.
- [ ] Document cleanup of disposable local data and hosted sessions.

## Acceptance criteria

- A fresh operator can follow `docs/LIVE_INTEGRATION_SMOKE.md` without undocumented setup.
- The browser run verifies the full create-to-review path rather than only `/health` or a model call.
- The evidence contains genuine provider identifiers and no synthetic fallback.
- Model provider, deployment/agent, commit SHA and timestamp are recorded.
- The test never auto-approves or releases a report.
- Failure artifacts explain whether the fault came from the app, a scholarly provider, authentication, quota or the model.

## Validation

```powershell
$env:RUN_LIVE_RESEARCH_E2E = '1'
$env:RESEARCH_BASE_URL = 'http://127.0.0.1:8015'
$env:EXPECTED_MODEL_PROVIDER = 'azure' # use 'foundry' for Task 06
npm run test:e2e:live
```

This run makes real network calls and remote model requests. It can incur Azure token charges and, for a hosted agent, session compute charges. Keep credentials out of Playwright output and retained artifacts.
