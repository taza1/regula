# Future Delivery Tasks and Architecture Review Gates

Last reviewed: 2026-10-14

## Purpose and baseline

This plan turns the remaining research-system roadmap into reviewable implementation tasks. It complements [the project completion plan](PROJECT_COMPLETION_PLAN.md) and [Azure task breakdown](AZURE_TASK_BREAKDOWN.md); it does not record architecture decisions or authorize cloud deployment.

The merged baseline supports local SQLite/FTS5 execution, scholarly providers, guarded full-text extraction, model-backed review, and a safe human-gated workflow. Quality work in the current roadmap is marked complete. The tasks below remain open. Keep local deterministic execution working while adding provider or cloud adapters. Foundry hosted-agent deployment is optional and must be chosen through its task gate.

## Architecture decision rule

Any task marked **Review required** must have a short ADR reviewed before implementing the architectural choice. An ADR must capture:

1. Problem, constraints, and current behavior to preserve.
2. Options considered, decision owner, tradeoffs, and why the choice fits the measured use case.
3. Data flow, trust boundaries, tenant isolation, data residency, retention/licensing, and telemetry implications.
4. Availability, latency, capacity, cost envelope, quotas, and failure/degraded-mode behavior.
5. Schema/index/API compatibility, migration or backfill, active-run pinning, rollback, and recovery plan.
6. Security/privacy review, test and evaluation plan, acceptance thresholds, and operational ownership.

A task may proceed without an ADR only when it stays behind an existing interface and does not change persistence, identity/trust boundaries, data handling, deployment topology, release behavior, or operational cost. Record that conclusion in the PR. Unresolved architecture choices stay explicit; this plan does not choose them on behalf of reviewers.

No production deployment, chargeable hosted-agent rollout, or persistent-resource provisioning is part of documentation approval. Those actions require an approved target, owner, cost limit, and deployment review.

## Task map

| ID | Priority | Task | Depends on | Architecture review |
| --- | --- | --- | --- | --- |
| FUT-001 | P0 | Decide retrieval, model, identity, and production boundaries | None | Required for each decision below |
| FUT-010 | P1 optional | Pilot hosted Foundry agent | FUT-001; model/review baseline | Required before deployment |
| FUT-020 | P1 | Add embedding and vector retrieval | FUT-001; retrieval gold set | Required |
| FUT-030 | P1 | Add Azure AI Search adapter | FUT-020; FUT-001 | Required |
| FUT-040 | P2 | Add production persistence and background execution | FUT-001; FUT-030 | Required |
| FUT-050 | P1 | Add browser Entra sign-in and session security | FUT-001 | Required |
| FUT-060 | P1 | Add independent model verification | FUT-001; current review evaluations | Required if provider/process changes |
| FUT-070 | P2 | Complete production observability and recovery | FUT-040; FUT-050 | Required for SLO and retention choices |
| FUT-080 | P1/P0 | Define production report governance and release | FUT-040; FUT-050; FUT-060; FUT-070 | Required |

P0 means a decision or safety prerequisite; P1 means pilot capability; P2 means production platform work after a pilot decision. Existing parent task references use IDs from `AZURE_TASK_BREAKDOWN.md`.

## FUT-001 — Decision records and measurable baseline

**Priority:** P0. **Review required:** Yes.

- [ ] Confirm whether direct Azure model access remains the supported first remote path and whether the hosted Foundry agent is worth a separate pilot. Keep the local/mock path usable.
- [ ] Decide vector storage and embedding ownership: local development implementation, managed index, or both; identify model/version, dimensions, chunking, content normalization, and re-embedding policy.
- [ ] Decide whether Azure AI Search is the production search service and which keyword/vector/hybrid capabilities are required for the first release.
- [ ] Decide production persistence, queue, object storage, and transaction/outbox boundaries; document invariants for runs, cancellation, revocation, approval, and release.
- [ ] Decide browser authentication modes, tenant mapping, project-role source, session model, and local-development identity behavior.
- [ ] Decide what qualifies as independent verification (separate model family/provider, deterministic checker, or both) and what data may be sent to each verifier.
- [ ] Baseline current local evaluation results, provider/model identifiers, prompt and index versions, latency, and cost where available. Store machine-readable results as CI/test artifacts, not as permanent claims without a date and commit.

**Validation and acceptance:** ADRs identify an owner and reviewers; unresolved alternatives are visible; the baseline can be reproduced from a clean checkout. No choice silently changes local defaults or enables release.

**Parent tasks:** TASK-001, TASK-004, TASK-006, TASK-012, TASK-013, TASK-018, TASK-031, TASK-035.

## FUT-010 — Optional hosted Foundry agent pilot

**Priority:** P1 optional. **Review required:** Yes, before any deployment.

- [ ] Record a go/no-go decision, non-production project, named operator, allowed region/data class, maximum spend/session duration, and rollback owner.
- [ ] Verify packaged files are allowlisted; record package digest, agent/model versions, settings, identity, and effective permissions.
- [ ] Use a dedicated least-privilege managed identity. Verify model invocation, endpoint access, network/DNS, telemetry permissions, quota, and idle-session shutdown.
- [ ] Make deployment repeatable and safe to preview; document how to inspect the planned change and retire/roll back a version.
- [ ] Run the same versioned model/review cases against direct Azure and the hosted agent. Keep prompts, evidence, settings, and thresholds equivalent; record latency, tokens, failures, and cost.
- [ ] Run the guarded browser flow with the expected provider explicitly set to Foundry. Confirm real scholarly sources, correct provider identification, review gates, redacted telemetry, and terminal state requiring human adjudication where appropriate.
- [ ] Exercise timeout, throttling, unavailable endpoint, malformed response, cancellation, and retry. A failed hosted call must not silently fall back or present itself as a successful Foundry run.

**Validation and acceptance:** Recorded browser trace and redacted result identify the hosted provider/version; all release-blocking cases pass the agreed repeated-run criteria; budget is within the approved limit; idle compute stops; rollback is demonstrated. No approval or publication is created by the smoke run.

**Parent tasks:** TASK-004, TASK-005, TASK-023, TASK-028, TASK-029.

## FUT-020 — Embeddings and vector retrieval

**Priority:** P1. **Review required:** Yes.

- [ ] Extend the versioned retrieval gold set with multi-domain queries, exact and recent items, sparse/no-result cases, known duplicates, contradictory findings, and expected identifiers. Keep held-out cases separate from tuning data.
- [ ] Define embedding interface and configuration: provider/model/version, dimensions, text normalization, chunk boundaries, maximum input, retry/rate-limit behavior, and cost telemetry.
- [ ] Store each vector's source/evidence ID, content hash, chunk/version, tenant/project scope, eligibility/revocation state, and embedding model metadata. Define deletion and rebuild behavior.
- [ ] Implement a local or test adapter behind the retrieval interface selected in FUT-001. Preserve FTS5/BM25 results and deterministic offline operation.
- [ ] Add vector candidate retrieval with mandatory tenant/project/run/eligibility filters before returning evidence. Define behavior when vector service or embeddings are missing or stale.
- [ ] Add hybrid ranking and configurable fusion/reranking only after recording a keyword-only baseline. Avoid unmeasured changes to source independence and contradiction handling.
- [ ] Add index rebuild/backfill and version switch procedures; active runs must retain their declared retrieval/index configuration while revoked evidence remains excluded.

**Validation and acceptance:** Compare keyword-only and hybrid retrieval on held-out gold cases. Report Precision@K, Recall@K, nDCG or MRR, date accuracy, duplicate leakage, source-independence grouping, contradiction discovery, provider errors, latency, and cost. Thresholds must be agreed and encoded before declaring a pass. Add tests for stale vectors, duplicate passages, missing embeddings, revoked items, cross-tenant IDs, provider outage, and rebuild interruption. Do not regress existing retrieval acceptance criteria without reviewer approval.

**Parent tasks:** TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-022, TASK-030, TASK-035.

## FUT-030 — Azure AI Search adapter

**Priority:** P1. **Review required:** Yes.

- [ ] Specify index schema, key strategy, analyzer/vector profiles, metadata fields, source and passage references, licence/provenance fields, and schema version.
- [ ] Implement the existing retrieval contract with Azure AI Search behind an adapter; keep local FTS5 available for local/offline mode.
- [ ] Enforce tenant, project, run, source eligibility, licence policy, and revocation filters in server-side queries. Do not trust client-supplied filters as authorization.
- [ ] Use managed identity and least privilege; define connection, retry, timeout, throttling, partial failure, and health reporting behavior.
- [ ] Implement idempotent upsert/delete, reconciliation against the source of truth, index build/rebuild, alias or version swap, and rollback.
- [ ] Define how keyword, vector, and optional semantic ranking combine, including provenance returned for each ranked passage.
- [ ] Measure expected index size, replicas/partitions, ingestion rate, query volume, region/network requirements, and monthly cost before selecting production capacity.

**Validation and acceptance:** Integration tests prove tenant isolation, revoked/deleted evidence exclusion, licence filtering, duplicate handling, partial provider failure reporting, idempotent reindex, and rollback. Compare adapter results against the local gold-set baseline; all differences are reported and explained. Infrastructure validation is repeatable without embedding secrets in templates or logs.

**Parent tasks:** TASK-004, TASK-006, TASK-012, TASK-013, TASK-031, TASK-035.

## FUT-040 — Production persistence and background execution

**Priority:** P2. **Review required:** Yes.

- [ ] Write storage invariants and workload estimates before selecting Cosmos partition keys, throughput, transaction boundaries, Blob retention/versioning, and Service Bus tier.
- [ ] Define repository interfaces and keep SQLite as the local adapter. Avoid leaking Cosmos-specific query semantics into application/domain behavior.
- [ ] Implement Cosmos records with tenant-scoped partition strategy, optimistic concurrency/ETags, transactional batches where supported, and explicit schema migration/versioning.
- [ ] Store source snapshots and release artifacts in private Blob Storage with immutable content hashes, metadata, retention/deletion policy, and licence-aware access.
- [ ] Implement Service Bus inbox/outbox delivery with idempotency keys, bounded retry/backoff, dead-letter handling, replay controls, cancellation, run epochs, and stale-result rejection.
- [ ] Define consistency/reconciliation behavior across database, blob, search index, and queue. Prevent any release from becoming visible before its manifest and approval invariants hold.
- [ ] Add staging deployment, data migration/backfill, export, backup/restore, and rollback procedures before production consideration.

**Validation and acceptance:** Adapter contract tests run against local and staging implementations. Concurrency and fault-injection tests cover duplicate/reordered messages, worker crash, queue replay, Blob failure, partial indexing, stale ETag, cancellation race, revocation race, and interrupted migration. No lost run state, cross-tenant read, duplicate release, or premature release is allowed. Restore and rollback are demonstrated from recorded backups.

**Parent tasks:** TASK-004, TASK-010, TASK-017, TASK-025, TASK-031, TASK-034, TASK-035.

## FUT-050 — Browser SSO and session security

**Priority:** P1 before shared browser pilot. **Review required:** Yes.

- [ ] Define Entra tenant/app registration, supported account types, redirect/logout URLs, local development mode, and project-role mapping.
- [ ] Implement OIDC authorization-code flow with PKCE using a supported library; validate signature, issuer, audience, tenant, expiry, nonce/state, and required claims.
- [ ] Map the authenticated principal to server-owned project membership and roles. Never accept tenant/user identity or authorization scope from query parameters or browser storage as proof.
- [ ] Choose cookie/session or token storage with expiry, renewal, logout, revocation, CSRF, SameSite/Secure/HttpOnly, CORS, and reverse-proxy behavior documented.
- [ ] Keep local development identity explicit and disabled in deployed environments; fail startup if an unsafe auth mode is configured outside local development.
- [ ] Add audit events for sign-in, denial, role changes, session revocation, and sensitive operations without recording tokens or unnecessary personal data.

**Validation and acceptance:** Browser tests cover sign-in success, invalid issuer/audience, wrong tenant, missing role, cross-project access, role removal, expired/revoked session, CSRF, logout, and local-only auth rejection in deployed mode. API tests confirm all sensitive routes derive authorization from validated server-side identity.

**Parent tasks:** TASK-003, TASK-005, TASK-027, TASK-031, TASK-032.

## FUT-060 — Independent model verification

**Priority:** P1 before any release path treats model review as sufficient. **Review required:** Yes.

- [ ] Decide independence boundary and provider/data policy. A second call to the same model with the same context is not independent verification.
- [ ] Define verifier input as a versioned claim ledger plus eligible evidence passages and provenance; limit unrelated draft/context data.
- [ ] Require structured findings by claim ID, with exact passage references, support/contradiction/uncertainty labels, rationale codes, and verifier model/prompt version.
- [ ] Keep verifier output advisory until deterministic application gates validate references, eligibility, required fields, and policy. It cannot approve or publish.
- [ ] Expand adversarial fixtures for unsupported claims, numerical errors, indirect evidence, conflicts, stale/retracted sources, selection bias, prompt injection, malformed output, and disagreement.
- [ ] Define repeated-run policy, case-level thresholds, disagreement handling, timeout/retry limits, budget, latency target, and fail-closed behavior for unavailable verifier.
- [ ] Store a redacted, reproducible evaluation bundle with input hashes, model/provider versions, prompts, settings, results, and cost/latency metadata.

**Validation and acceptance:** Run paired repeated evaluations against the current review path and independent verifier on a held-out set. Report per-case pass rates and confidence/variation; any mandatory failure blocks promotion. Verify every finding points to an eligible passage and that unsupported or contradictory material claims remain blocked. Test provider outage, timeout, disagreement, malformed output, and prompt injection. Model output alone cannot bypass deterministic release gates.

**Parent tasks:** TASK-018, TASK-020, TASK-021, TASK-022, TASK-023, TASK-028, TASK-030.

## FUT-070 — Observability, SLOs, and recovery operations

**Priority:** P2. **Review required:** Yes.

- [ ] Set pilot SLOs, availability/latency targets, queue age, recovery time (RTO), data loss window (RPO), and operational owners.
- [ ] Add correlated traces and metrics for request/run/provider/model/search/queue/storage outcomes, latency, retries, tokens/cost, evaluation blocks, and recovery state.
- [ ] Redact prompts, source passages, tokens, personal data, and private identifiers by default. Document narrowly scoped exceptions and retention.
- [ ] Add dashboards and actionable alerts for provider failures, queue backlog/dead letters, budget/quota, stale jobs, storage/index divergence, failed backups, and release-gate failures.
- [ ] Write operator runbooks for incident triage, provider disablement, queue replay, index rebuild, credential/role rotation, restore, rollback, and user communication.
- [ ] Set budget alerts and hard limits for model and hosted-agent calls; verify behavior when limits are reached.
- [ ] Exercise restore, failover/degraded mode, and rollback in staging on a recurring schedule and retain evidence.

**Validation and acceptance:** Synthetic failures trigger the correct alerts and runbooks. Telemetry review confirms sensitive content is absent. Restore/rollback meets the agreed RTO/RPO; monitoring distinguishes provider outage from relevance failure and user/data-policy rejection.

**Parent tasks:** TASK-004, TASK-006, TASK-024, TASK-029, TASK-031, TASK-035.

## FUT-080 — Production report governance and release

**Priority:** P1 for internal publishing, P0 before external publishing. **Review required:** Yes.

- [ ] Name research, reviewer, approver/publisher, withdrawal, and audit responsibilities; prohibit self-approval where policy requires separation.
- [ ] Bind approval to immutable report content, evidence manifest, source licences, retrieval/index version, model/verifier/prompt versions, policy, and evaluation results.
- [ ] Define copyright, privacy, data retention, acceptable use, source withdrawal/retraction, correction, and report withdrawal policies.
- [ ] Implement authenticated private release reads and withdrawal/tombstone behavior; keep export/public links disabled until separately approved.
- [ ] Threat-model SSRF, cross-tenant access, prompt injection, model/provider data handling, queue poisoning, telemetry, supply chain, and approval bypass.
- [ ] Establish promotion checklist, rollback owner, incident path, and evidence retention before enabling release in any shared environment.

**Validation and acceptance:** Adversarial and fault-injection tests prove that edits after approval, stale approval, missing licence, revoked evidence, unsupported material claim, verifier failure, unauthorized publisher, manifest mismatch, and withdrawal block visibility. A reviewer can reproduce the exact claim-to-passage and approval chain for any released report.

**Parent tasks:** TASK-023, TASK-025, TASK-027, TASK-031, TASK-032, TASK-033, TASK-034.

## Suggested sequence and merge gates

1. **FUT-001:** Agree decision owners, ADRs, baselines, and cost/security boundaries.
2. **FUT-020:** Evaluate embeddings/vector retrieval behind the local interface while preserving FTS5.
3. **FUT-030:** Add and compare the Azure AI Search adapter after the vector/index ADR.
4. **FUT-060:** Evaluate independent verification against current model/review fixtures; keep release blocking on failures.
5. **FUT-010:** If selected and separately budgeted, run a bounded hosted-agent pilot.
6. **FUT-050:** Complete browser identity before shared-user pilot.
7. **FUT-040 + FUT-070:** Build production storage/execution and operational recovery in staging after cost and invariants are reviewed.
8. **FUT-080:** Enable a release path only after governance, security, recovery, and human approval gates pass.

Each implementation PR should name its FUT task IDs, link its ADR (or explain why no architecture choice changes), include the relevant deterministic and integration/evaluation evidence, and update `TODO.md` only when acceptance criteria have actually passed. Live or chargeable checks must be opt-in, budget-bounded, redacted, and clearly distinguished from deterministic CI.
