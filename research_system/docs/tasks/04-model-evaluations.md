# Task 04: Build model and review evaluations

Priority: P0 before release

Related work: TASK-016, TASK-018 through TASK-023, TASK-028, TASK-030

Status: Initial framework present

## Outcome

Model-backed synthesis, fact-checking and critical review reliably block unsupported or unsafe reports and preserve a traceable claim-to-evidence relationship.

## Required cases

- Unsupported factual and causal claims.
- Direct and partial entailment.
- Numerical or population mismatch.
- Selection bias and overgeneralization.
- Stale or retracted evidence.
- Conflicting evidence and unresolved contradictions.
- Prompt injection embedded in source text.
- Citation mismatch, missing evidence and ineligible evidence.
- Tool/provider failure, cancellation and incomplete runs.

## Implementation checklist

- [ ] Expand `evals/model_cases.json` with release-critical and diagnostic cases.
- [ ] Record model/deployment, prompt and schema versions, settings, latency and token use.
- [ ] Run non-deterministic cases repeatedly and define tolerated variance.
- [ ] Require deterministic gates for citation existence, hashes, scope, eligibility and approval state.
- [ ] Compare same-model independent calls with a separate evaluator or deterministic checker where practical.
- [ ] Fail promotion when any mandatory blocker is missed, regardless of aggregate score.
- [ ] Add redacted failure artifacts that make regressions reproducible.

## Acceptance criteria

- Every material claim maps to eligible evidence passages.
- Unsupported causal claims, prompt injection, stale evidence and unaddressed conflicts block approval.
- All release-critical cases pass the agreed threshold over repeated runs.
- Model scores cannot override application-owned mandatory gates.
- Regression output identifies the failed case, expected behavior and observed behavior without exposing secrets or source text disallowed by policy.

## Validation

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest -q tests\test_review_publication.py tests\test_quality_evals.py
python scripts\run_quality_evals.py --suite model --output data\model-eval.json
```

The live model suite is chargeable for Azure or Foundry deployments. Run it through a protected, budget-limited workflow and record token use and estimated cost with the result.
