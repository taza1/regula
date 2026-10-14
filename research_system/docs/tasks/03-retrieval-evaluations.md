# Task 03: Build repeatable retrieval evaluations

Priority: P0

Related work: TASK-013, TASK-022, TASK-023, TASK-028

Status: Initial framework present

## Outcome

Retrieval quality is measured against a versioned gold set so connector or ranking changes cannot be accepted on anecdotal search results.

## Evaluation set

Include multiple research domains and the following case types:

- Exact DOI and exact-title lookup.
- Broad topical and sparse queries.
- Recent-research and strict date-boundary queries.
- Known contradictory studies and multiple publications from one study.
- Negative or no-result queries.
- Provider timeout, rate-limit and partial-outage behavior.
- Abstract-only and permitted full-text comparisons.

Each stable case must record expected identifiers, relevant alternatives, date rules, independence groups and the reason the case is included. Cases without expected identifiers may test broad heuristics but cannot establish recall.

## Metrics

- Recall at K and precision at K.
- Mean reciprocal rank or nDCG.
- Date-filter accuracy and stale-evidence rate.
- Duplicate rate and independent-source-group count.
- Contradictory-evidence discovery rate.
- Per-provider latency, timeout, rate-limit and empty-result rate.
- Full-text availability and abstract-only rate.

## Implementation checklist

- [ ] Expand `evals/retrieval_cases.json` and version its schema.
- [ ] Separate tuning cases from held-out acceptance cases.
- [ ] Define pass thresholds with the product/research owner.
- [ ] Emit machine-readable metrics and a concise human summary.
- [ ] Distinguish provider availability failures from relevance regressions.
- [ ] Add a scheduled or protected workflow with bounded requests.
- [ ] Retain dated artifacts with commit SHA and provider/query versions.

## Acceptance criteria

- The same fixture version produces comparable metrics across commits.
- Every supported provider has live success and failure-path evidence.
- Threshold failures return a non-zero exit code.
- Ranking changes show held-out improvement or no material regression.
- Source independence and contradictory evidence are measured, not inferred from source count.

## Validation

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest -q tests\test_quality_evals.py
$env:SOURCE_CONNECTOR = 'scholarly'
python scripts\run_quality_evals.py --suite retrieval --output data\retrieval-eval.json
```

The live run uses public provider APIs and can consume rate-limit allowance. Store the output as a CI or release artifact rather than committing transient results as permanent performance claims.
