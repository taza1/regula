# Remaining delivery tasks

Last reviewed: 2026-09-27

These task specifications turn the six agreed research-quality improvements into independently reviewable work items. A task is complete only when its acceptance criteria pass and its evidence is attached to the pull request or controlled test run. Existing code or a successful health check alone does not complete a task.

| Order | Task | Priority | Current position |
| --- | --- | --- | --- |
| 1 | [Improve scholarly search relevance](01-search-relevance.md) | P0 | Provider-specific query and ranking changes exist; broader live evaluation is still required. |
| 2 | [Complete licensed full-text retrieval](02-licensed-full-text.md) | P1 | Permission checks and extraction paths exist; coverage and governance remain incomplete. |
| 3 | [Build repeatable retrieval evaluations](03-retrieval-evaluations.md) | P0 | Initial fixtures and runner exist; gold-set depth and release thresholds remain open. |
| 4 | [Build model and review evaluations](04-model-evaluations.md) | P0 | Initial adversarial cases exist; repeated-run thresholds and regression evidence remain open. |
| 5 | [Operationalize the live Playwright smoke test](05-live-playwright-smoke.md) | P0 | Guarded test and run guide exist; a protected repeatable execution and retained evidence are still needed. |
| 6 | [Deploy and validate the Foundry hosted agent](06-foundry-hosted-agent.md) | P1 | Package and deployment tooling exist; the packaged agent has not been deployed and tested end to end. |

## Dependency order

1. Tasks 1 and 3 should progress together: ranking changes must be measured against versioned retrieval cases.
2. Task 2 can proceed in parallel, but its sources must be added to Task 3 before full-text support is considered proven.
3. Task 4 depends on stable evidence contracts from Tasks 1–3.
4. Task 5 is the acceptance path for the direct Azure model and later the hosted agent.
5. Task 6 uses Task 5 as its final browser-level verification.

Production Azure data-plane work and report governance remain tracked in [the project completion plan](../PROJECT_COMPLETION_PLAN.md). They are intentionally outside these six quality and integration tasks.
