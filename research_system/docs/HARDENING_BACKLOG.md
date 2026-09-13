# Research-system hardening backlog

Created: 2026-09-12. Updated: 2026-09-12. Status: implemented locally; hosted CI verification is pending push.

These repository backlog entries extend the existing [Azure task breakdown](AZURE_TASK_BREAKDOWN.md); they are not GitHub issues. The audit compared research branch `31864b2` with scholarly-connectors branch `97f18e3`; the connector work is now merged and verified locally.

| ID | Priority | Task | Parent tasks | Status |
| --- | --- | --- | --- | --- |
| HARD-001 | P0 | Harden document fetching | TASK-008, TASK-031 | Implemented and locally tested |
| HARD-002 | P1 | Report provider failures explicitly | TASK-007, TASK-015 | Implemented and locally tested |
| HARD-003 | P1 | Fix arXiv recency retrieval | TASK-007 | Implemented and locally tested |
| HARD-004 | P1 | Enforce snapshot immutability | TASK-010 | Implemented and locally tested |
| HARD-005 | P1 | Add research-system CI | TASK-024 | Workflow added; hosted run pending |
| HARD-006 | P2 | Refresh Azure plan and completion labels | TASK-001 | Completed for this baseline |

## HARD-001: Harden document fetching

- [x] Validate permitted schemes, domains, and resolved IPv4/IPv6 addresses before connecting; block private, loopback, link-local, reserved, and cloud metadata destinations.
- [x] Validate every redirect target and prevent DNS changes from bypassing address checks at connection time.
- [x] Stream downloads with enforced byte limits, bounded redirects, and request/total time limits; do not buffer an unlimited response before checking its size.
- [x] Test allowed retrieval, forbidden redirect targets, private addresses, oversized streams without Content-Length, and malformed responses. Further network fault injection remains part of TASK-008.

Done when forbidden destinations are never contacted and oversized or stalled transfers terminate within configured limits. Complete before enabling full-document fetching for untrusted source URLs.

## HARD-002: Report provider failures explicitly

- [x] Record provider-level success, empty result, timeout, rate-limit exhaustion, and failure outcomes without exposing credentials or sensitive response bodies.
- [x] Preserve successful providers' results while returning visible partial-failure status; distinguish failures from a successful search with no matches.
- [x] Label local fixture fallback explicitly in API results and provenance.
- [x] Test mixed success/failure, all-provider failure versus empty results, retry behavior, and fallback behavior.

Done when callers can distinguish provider outages from missing research evidence. Applies to the combined connector on the scholarly-connectors branch.

## HARD-003: Fix arXiv recency retrieval

- [x] Apply the requested publication window in the arXiv query and use appropriate date sorting for latest/recent questions.
- [x] Use bounded pagination to find eligible results rather than filtering only the first relevance-ranked page.
- [x] Preserve explicit date ranges and define the default latest-query window consistently with other providers.
- [x] Test query date boundaries, sorting, malformed XML, and payload limits. Live API pagination still requires integration validation; the 2026-09-12 check timed out from the development environment.

Done when recent papers within the requested window are discoverable without being hidden by older, higher-relevance results.

## HARD-004: Enforce snapshot immutability

- [x] Add atomic insert-only or compare-and-reject snapshot persistence instead of unconditional upserts.
- [x] Treat identical retries as idempotent without replacing the original retrieval timestamp or payload.
- [x] Reject conflicting payloads under an existing snapshot ID; changed source content produces a new content-addressed snapshot ID.
- [x] Test identical retries and conflicting writes. Production concurrency remains part of Cosmos implementation.

Done when persisted snapshots cannot be silently overwritten and references continue to resolve to their original content.

## HARD-005: Add research-system CI

- [x] Add CI coverage for research-system pull requests and pushes, preserving the existing OPA workflow.
- [x] Install declared Python and Node dependencies and Playwright Chromium; run Python tests and browser tests against a managed local server.
- [x] Use deterministic mock/local providers so ordinary CI requires no Azure credentials or live scholarly APIs.
- [x] Fail the workflow on test failures and generate a Python test report. Hosted verification is pending push.

Done when a CI run verifies both Python and Playwright suites and a failing research-system test produces a failing check. Coordinate the GitHub workflow with the existing TASK-024 Azure DevOps delivery plan.

## HARD-006: Refresh Azure plan and completion labels

- [x] Reconcile the delivery plan, task breakdown, roadmap, and usage documentation against identified branch/commit baselines.
- [x] Distinguish implemented, integrated, tested, and deployed work; date verification evidence.
- [x] Correct claims about header-based development identity, snapshot immutability, state concurrency, and reviewed synthesis.
- [x] Keep unverified Azure inventory clearly dated rather than presenting it as current deployment evidence.

Done when documents agree about capabilities and remaining guarantees, including connector integration status. Documentation review must not imply deployment or completed independent specialist signoff.

## Execution order

Review the connector branch and address HARD-001 before enabling full-text fetching. HARD-002 and HARD-003 belong with connector integration. HARD-004 and HARD-005 can proceed independently. Complete HARD-006 against the verified integration baseline.
