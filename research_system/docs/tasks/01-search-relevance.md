# Task 01: Improve scholarly search relevance

Priority: P0

Related work: TASK-007, TASK-013, TASK-015

Status: In progress

## Outcome

OpenAlex, Crossref and arXiv receive queries suited to their APIs and return relevant, date-correct results in a stable order. A provider outage or weak result set remains visible to the user.

## Scope

- Translate the research question into provider-specific search terms, identifiers, date filters and pagination parameters.
- Preserve quoted phrases, DOI/title lookups and domain-specific terms where the provider supports them.
- Improve arXiv ordering using field-aware search, submitted-date constraints and bounded pagination.
- Normalize scores without implying that scores from different providers are directly comparable.
- Deduplicate publications while retaining provider provenance and evidence-independence groups.
- Keep partial-provider outcomes explicit in the API and dashboard.

## Implementation checklist

- [ ] Define query-translation rules and examples for OpenAlex, Crossref and arXiv.
- [ ] Add exact DOI and exact-title paths before broad keyword expansion.
- [ ] Add controlled synonym and acronym expansion with a recorded query plan.
- [ ] Rank exact identifiers/titles first, then semantic or lexical relevance, then recency when requested.
- [ ] Penalize missing abstracts, retracted records and duplicate versions without hiding them from diagnostics.
- [ ] Add timeout, rate-limit, empty-result and malformed-response regression tests.
- [ ] Tune only against a training subset and report results on held-out cases.

## Acceptance criteria

- Exact DOI and stable exact-title cases return the expected work in the top three results.
- Date-bounded cases contain no out-of-range evidence.
- arXiv relevance and reciprocal-rank thresholds defined by Task 03 pass on held-out cases.
- Duplicate versions do not inflate source-independence counts.
- Every provider outcome is recorded as success, empty, timeout, rate-limited or failed.
- No synthetic or placeholder passage can enter a live research run.

## Validation

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest -q tests\test_source_discovery.py tests\test_quality_evals.py
$env:SOURCE_CONNECTOR = 'scholarly'
python scripts\run_quality_evals.py --suite retrieval --output data\retrieval-eval.json
```

Retain the fixture version, commit SHA, provider response status, metrics and redacted result JSON. OpenAlex, Crossref and arXiv metadata access does not currently require paid accounts, but provider rate limits and acceptable-use requirements still apply.
