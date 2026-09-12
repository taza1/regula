# Azure Task Breakdown

Last reviewed: 2026-09-12

This breakdown maps the original 35 task IDs into an execution order that gets the system working locally first, then on Azure, then through review and internal release.

## Wave 0: Stabilize Planning Baseline

| Task | Work | Acceptance |
| --- | --- | --- |
| TASK-001 | Keep repo layout, docs index, run scripts, and environment conventions stable. | New developer can run tests and local API from `research_system` without undocumented setup. |
| TASK-002 | Implement versioned Pydantic contracts for projects, run controls, sources, evidence, claims, findings, approvals, releases, manifests, and configuration snapshots. | Invalid scope, enum, version, and transition payloads are rejected. |
| TASK-003 | Complete OpenAPI endpoints for status, cancellation, evidence inspection, findings, adjudication, approval, internal release reads, and withdrawal. | API distinguishes unauthorized, stale version, stopped run, pending release, and withdrawn release. |
| TASK-035 | Add compatible schema/config/index migration, rollback, and active-run pinning rules early. | Active runs stay pinned; revocations still apply; rollback path is tested before pilot. |

## Wave 1: Security and Run Control First

| Task | Work | Acceptance |
| --- | --- | --- |
| TASK-031 | Implement project authorization and data-policy enforcement across API, storage, search, queues, model calls, and telemetry. | Two-project adversarial tests pass; missing policy blocks execution. |
| TASK-014 | Implement scope confirmation, budgets, source limits, and configuration snapshots. | Planner output requires explicit confirmation; budgets and limits are persisted and enforced. |
| TASK-017 | Implement deterministic orchestration, run epochs, legal state transitions, retries, cancellation, and stale-result rejection. | Cancelled/terminal runs are not revived; late worker output is rejected. |
| TASK-005 | Implement least-privilege managed identity and RBAC model. | No app path requires stored Azure keys; role tests fail closed. |

## Wave 2: Real Local Research Pipeline

| Task | Work | Acceptance |
| --- | --- | --- |
| TASK-007 | Add scholarly API clients for OpenAlex, Crossref, and arXiv. | Real metadata is normalized with source attribution, IDs, rate-limit handling, and retries. |
| TASK-008 | Add governed crawler only for allowlisted permitted web content. | Robots, SSRF, size/time limits, content-type checks, and source policy are enforced. |
| TASK-009 | Separate source deduplication from evidence independence. | Repeated publications from one study/dataset count as one origin. |
| TASK-010 | Store immutable raw source snapshots and retrieval metadata. | Hashes and retrieval timestamps allow reproduction/audit. |
| TASK-011 | Extract passages with section/page/offset metadata where possible. | Citations can point to exact source locations. |
| TASK-030 | Implement evidence quality, origin, and sufficiency assessment. | Unsupported generalizations and unresolved contradictions block release readiness. |

## Wave 3: Retrieval

| Task | Work | Acceptance |
| --- | --- | --- |
| TASK-012 | Build Azure AI Search indexes for evidence text, vectors, metadata, and citation locations. | Index definitions are versioned and deployable through IaC. |
| TASK-013 | Implement hybrid retrieval with project/run filters. | Keyword, vector, semantic, and metadata-filtered tests meet baseline precision/recall. |

## Wave 4: Agents and Synthesis

| Task | Work | Acceptance |
| --- | --- | --- |
| TASK-015 | Implement ResearchAgent/source search behavior including contradictory evidence search. | Plans generate accepted evidence tasks and record unavailable/failed source outcomes. |
| TASK-016 | Implement evidence-grounded synthesis and material claim ledger. | Every material claim references eligible passages or becomes `insufficient_evidence`. |
| TASK-018 | Implement independent fact-checking. | False or unsupported claims produce findings tied to claim IDs and evidence. |
| TASK-019 | Implement citation validation. | Missing, stale, or mismatched citations block release readiness. |
| TASK-020 | Implement critical review. | Methodological limitations and contradictions are recorded and gated. |
| TASK-021 | Implement safety and prompt-injection review. | Untrusted source instructions cannot control agents; privacy/security issues block release. |

## Wave 5: Azure Foundation

| Task | Work | Acceptance |
| --- | --- | --- |
| TASK-004 | Provision Foundry, Hosted Agent runtime, Blob Storage, Azure AI Search, Cosmos DB, Service Bus, Key Vault, and Application Insights with Bicep/azd. | Empty dev resource group deploys reproducibly. |
| TASK-006 | Add per-environment parameters, naming, tags, network policy, and budget controls. | Dev/test/prod settings are explicit and reviewed. |
| TASK-024 | Add Azure DevOps Pipelines for lint, tests, security scan, IaC validation, deployment, smoke, and rollback gates. | Main branch cannot deploy broken contracts, insecure config, or failing tests. |
| TASK-028 | Add shadow evaluation mode against real runs without publication. | Shadow results are visible but cannot publish. |

## Wave 6: Gates, Approval, and Release

| Task | Work | Acceptance |
| --- | --- | --- |
| TASK-022 | Build gold datasets and adversarial fixtures. | Fixtures cover support, contradiction, weak evidence, bad citations, prompt injection, and source-policy failures. |
| TASK-023 | Implement deterministic and Foundry semantic evaluators plus application-owned gates. | High aggregate score cannot bypass an unsupported material claim or mandatory failure. |
| TASK-027 | Implement human revision, rejection, and separate-Publisher approval bound to bundle digest. | Self-approval, stale approval, unauthorized role, and post-approval edits are rejected. |
| TASK-033 | Implement constrained adjudication. | Permitted false-positive/limitation dispositions are recorded; forbidden waivers remain blocked. |
| TASK-025 | Generate signed/versioned manifests for sources, evidence, model, prompt, tool, index, config, evaluations, and approvals. | Manifest verifies artifact hashes and approval binding. |
| TASK-034 | Implement release intent, verified private artifact write, conditional Cosmos commit, inbox/outbox, and reconciliation. | Fault injection proves no premature visibility, no duplicate release, and correct cancellation/revocation races. |
| TASK-032 | Implement authenticated internal release discovery, reads, and withdrawal. | No anonymous/export access exists; withdrawal/revocation blocks future reads. |

## Wave 7: UI and Pilot

| Task | Work | Acceptance |
| --- | --- | --- |
| TASK-026 | Build workbench screens for projects, scope, progress, evidence, draft, review, approval, release, recovery, and withdrawal. | Browser tests cover success, partial failure, insufficient evidence, budget exhaustion, cancellation, invalidation, and withdrawal. |
| TASK-029 | Run limited pilot rollout with dashboards, runbooks, rollback, and acceptance evidence. | Pilot starts only after all mandatory gates, security tests, and operational checks pass. |

## Immediate Backlog

These are the first implementation tickets I would open:

| Priority | Ticket | Depends on | Done when |
| --- | --- | --- | --- |
| Done | Replace query-string tenant/user trust with an auth context dependency and local dev identity adapter. | TASK-002, TASK-003 | Direct cross-tenant API calls fail in tests. |
| Done | Add legal run transition table and local revision checks. | TASK-002, TASK-017 | Confirming, cancelling, and local execution cannot revive terminal runs. |
| P0 | Add run epochs/stale worker protection for background execution. | TASK-002, TASK-017 | Retried or late worker results are rejected after cancellation, retry, policy change, or successor run creation. |
| Done | Harden OpenAlex connector and add Crossref/arXiv behind the same source interface. | TASK-007 | Local discovery returns normalized metadata with retries, attribution, and visible provider outcomes. |
| Done | Persist immutable local source snapshots and abstract-level passage records. | TASK-010, TASK-011 | Snapshot conflicts are rejected and evidence contains source and passage references. Precise PDF page/section coordinates remain open under TASK-011. |
| P1 | Add local FTS retrieval, then Azure AI Search schema. | TASK-012, TASK-013 | Search returns scoped, ranked evidence and fixture precision/recall thresholds pass. |
| Done | Implement deterministic local draft skeleton plus claim ledger. | TASK-016, TASK-030 | Drafts cite eligible evidence and claims remain pending review. |
| P1 | Implement reviewed LLM synthesis with insufficiency/contradiction handling. | TASK-016, TASK-030 | Unsupported claims are tracked as insufficient evidence and cannot enter a release-ready draft. |
| P1 | Implement citation validator and fact-checker. | TASK-018, TASK-019 | Bad citation and unsupported-claim fixtures block release readiness. |
| P1 | Add Bicep/azd foundation for dev. | TASK-004, TASK-005, TASK-006 | Empty resource group deploys all required services with managed identities. |
| P2 | Implement Service Bus workers and stale-result rejection. | TASK-017, TASK-004 | Duplicate/retried messages are idempotent and cancelled runs reject late output. |
| P2 | Implement approval, manifest, and release protocol. | TASK-023, TASK-025, TASK-027, TASK-034 | Fault injection proves release invariants. |

## Audit Follow-up Subtasks (2026-09-12)

All six entries are implemented locally. The hosted HARD-005 workflow run remains pending until push. Detailed scope and acceptance criteria are in the [hardening backlog](HARDENING_BACKLOG.md).

| Subtask | Priority | Work | Parent tasks |
| --- | --- | --- | --- |
| HARD-001 | P0 | Harden document fetching: redirects, resolved addresses, and streaming limits. | TASK-008, TASK-031 |
| HARD-002 | P1 | Surface provider failures and partial results. | TASK-007, TASK-015 |
| HARD-003 | P1 | Fix arXiv recency queries and pagination. | TASK-007 |
| HARD-004 | P1 | Enforce snapshot immutability; existing persistence does not guarantee it. | TASK-010 |
| HARD-005 | P1 | Add research-system Python/Playwright CI alongside OPA checks. | TASK-024 |
| HARD-006 | P2 | Reconcile Azure plan and completion labels with verified branch state. | TASK-001 |

Local snapshot immutability is covered by retry and conflicting-write regression tests. Production Blob/Cosmos immutability remains part of the Azure implementation.

## Acceptance Test Matrix

| Area | Must pass before pilot |
| --- | --- |
| Local API | Project/run/plan/confirm/execute/search flow; negative state transitions; direct auth bypass attempts. |
| Source discovery | OpenAlex/Crossref/arXiv success, timeout, rate limit, no result, duplicate source, and source-policy rejection. |
| Evidence | Immutable hash checks, passage coordinates, license/source-use filtering, independence grouping. |
| Retrieval | Keyword/vector/semantic/hybrid ranking, tenant/project/run filtering, revoked evidence exclusion. |
| Synthesis | Material claim ledger, exact citation references, contradiction handling, insufficient evidence. |
| Review | Fact-check, citation validation, critical review, safety/prompt-injection review, constrained adjudication. |
| Release | Stale approval, self-approval, storage failure, manifest mismatch, lost response, duplicate message, cancellation race. |
| Security | Entra auth, project membership, least privilege, queue poisoning, search/blob authorization, telemetry redaction. |
| Operations | Readiness, health, queue depth, dead letters, model errors, source failures, rollback, recovery dashboard. |
| UI | Scope confirmation, progress, evidence, revision, approval, release, withdrawal, and every non-success outcome. |

## Specialist Review Note

The requested parallel specialist review was attempted. Backend, Azure/DevOps, and security agents all hit a usage-limit error before final reports. This breakdown includes their partial findings plus direct repo/spec/docs verification, but it should not be treated as independently signed off.
