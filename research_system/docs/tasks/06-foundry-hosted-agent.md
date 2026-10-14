# Task 06: Deploy and validate the Foundry hosted agent

Priority: P1

Related work: TASK-004 through TASK-006, TASK-021, TASK-024, TASK-028

Status: Packaging exists; deployment and end-to-end validation pending

## Outcome

The packaged `regula-research-review` agent runs in the approved Microsoft Foundry development project and passes the same live research and review gates as direct Azure model access.

## Preconditions

- A named Azure subscription/project owner approves the target, budget and data residency.
- The model deployment, quota, spending alert and maximum test cost are recorded.
- A dedicated managed identity has only the model invocation and approved telemetry permissions.
- Tasks 04 and 05 have stable evaluation and smoke-test criteria.

The proposed non-production target is `foundry-agent-dev`; recheck the inventory immediately before deployment. Do not modify unrelated saved agents.

## Implementation checklist

- [ ] Build the whitelist-only package and record its SHA-256 hash.
- [ ] Run `hosted_agent/deploy.py` without `--apply` and review the proposed resources.
- [ ] Confirm the 1 CPU, 2 GiB and 120-second idle configuration and expected cost behavior.
- [ ] Deploy a version only after the target and cost envelope are approved.
- [ ] Verify activation, endpoint authorization, DNS/egress, model access and timeouts.
- [ ] Run the live Playwright test with `EXPECTED_MODEL_PROVIDER=foundry`.
- [ ] Compare evidence and mandatory review gates with the direct Azure path.
- [ ] Verify telemetry redaction and record token use, session duration and cost.
- [ ] Test idle deprovisioning, rollback and retirement of the test version.

## Acceptance criteria

- The browser-driven run records `MODEL_PROVIDER=foundry` and the expected packaged agent/version.
- Real scholarly evidence is retrieved and all mandatory review gates execute.
- Direct Azure and hosted-agent paths agree on application-owned gate outcomes for the same fixtures.
- Logs contain no credentials, access tokens, personal data, prompt text or document content beyond the approved telemetry policy.
- Idle compute deprovisions as configured and rollback instructions are tested.
- The deployment evidence includes package hash, version, commit SHA, timestamps, token use and measured cost.

## Validation

```powershell
python hosted_agent\package_agent.py
python hosted_agent\deploy.py

# After an approved deployment is active and the local API uses MODEL_PROVIDER=foundry:
$env:RUN_LIVE_RESEARCH_E2E = '1'
$env:RESEARCH_BASE_URL = 'http://127.0.0.1:8015'
$env:EXPECTED_MODEL_PROVIDER = 'foundry'
npm run test:e2e:live
```

The packaging and dry-run steps are local. Applying the deployment creates a chargeable Azure agent version; model calls also incur token charges. Deployment approval must use a current cost estimate and a bounded test budget.
