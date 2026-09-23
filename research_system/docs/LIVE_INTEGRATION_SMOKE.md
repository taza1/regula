# Live scholarly and Foundry smoke test

This opt-in Playwright test verifies the complete local API path against real scholarly providers and a real Azure or hosted Foundry model. It creates disposable local project/run records and makes chargeable model calls. It never approves or releases a report.

## Direct Azure model

Start the API in one terminal:

```powershell
az login
.\run_azure.ps1 -Endpoint 'https://your-resource.openai.azure.com' -Deployment 'gpt-5.6-sol' -Port 8015
```

Run the smoke test in another terminal:

```powershell
$env:RUN_LIVE_RESEARCH_E2E = '1'
$env:RESEARCH_BASE_URL = 'http://127.0.0.1:8015'
$env:EXPECTED_MODEL_PROVIDER = 'azure'
npm run test:e2e:live
```

## Hosted Foundry agent

After an agent version is active, start the API with `MODEL_PROVIDER=foundry`, `FOUNDRY_PROJECT_ENDPOINT`, and `FOUNDRY_AGENT_NAME`. Then set `EXPECTED_MODEL_PROVIDER=foundry` and run the same Playwright command.

The test fails unless the dashboard loads, the selected provider is remote, the source connector is exactly `scholarly`, all three provider outcomes are present, evidence is non-synthetic, model review completes, and the run reaches either `awaiting_approval` or the safe `adjudication_required` state.

## Quality evaluations

Run live retrieval fixtures with the configured source connector:

```powershell
$env:SOURCE_CONNECTOR = 'scholarly'
python scripts\run_quality_evals.py --suite retrieval --output data\retrieval-eval.json
```

Run the six model fixtures after configuring `MODEL_PROVIDER=azure`, `foundry`, or `local_proxy`:

```powershell
python scripts\run_quality_evals.py --suite model --output data\model-eval.json
```

The model suite checks unsupported claims, direct entailment, selection bias, prompt injection in evidence, stale evidence, and conflicting evidence. A non-passing case exits with status 1.
