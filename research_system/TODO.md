# Project Roadmap

## Current checkout status (2026-10-11)

- This checkout is `feature/research-dashboard-execution` at `31b70fa`, pushed to `origin/feature/research-dashboard-execution`. No pull request has been created yet.
- The branch is based on `c466d58` and is 11 commits behind `origin/master` (`2b0831e`). The newest branch tip is `feature/research-quality-evals` at `45bea89`, which adds research-quality task breakdowns on top of the newer master line.
- The dashboard and worker implementation matches the feature merged into `origin/master`; this branch carries its local verification and dashboard journey tests.
- Verification in this checkout: `python -m pytest tests -q` -> 45 passed; `npm run test:e2e` -> 4 passed, including dashboard create → plan → execute → inspect. Execution reaches `reviewing` with a draft ready; human review is still required.
- First follow-up: reconcile this branch with the newer `origin/master`/quality-evaluation line, then rerun tests. Newer review/release and evaluation implementation must not be counted as present in this older branch until integrated.

## Completed

- [x] Create FastAPI application and Swagger documentation
- [x] Add project and research-run lifecycle endpoints
- [x] Add mock and Azure AI planning clients
- [x] Persist local state in SQLite
- [x] Persist tenant/project/run-scoped evidence
- [x] Add deterministic offline source discovery and ingestion
- [x] Add OpenAlex paper discovery with latest-query recency handling
- [x] Add ranked local evidence search
- [x] Add local auth headers, project membership checks, and legal run-state transitions
- [x] Add canonical source deduplication, local snapshots, passage records, draft skeleton, and claim ledger
- [x] Add Python and Playwright test coverage
- [x] Add local and Azure launcher scripts

## Next milestone: real source discovery

- [x] Add OpenAlex connector
- [x] Add Crossref connector
- [x] Add arXiv connector
- [x] Normalize source metadata and identifiers
- [x] Enforce approved and excluded domain policies
- [x] Add retries, rate limits, and source attribution

## Evidence pipeline

- [x] Download HTML and PDF documents
- [x] Extract clean text and passages
- [x] Calculate content hashes and detect local source duplicates
- [x] Store source metadata and local snapshot artifacts
- [x] Add abstract-level passage metadata and citation references
- [x] Archive full-text extraction metadata and content-addressed snapshots

## Search and research generation

- [x] Add SQLite FTS5 search with BM25 ranking and scoped eligibility filters
- [ ] Add embeddings and vector retrieval
- [ ] Add Azure AI Search adapter
- [x] Implement durable local background run workers
- [x] Add research workspace dashboard for planning, execution, polling, and result inspection
- [x] Generate deterministic local claim ledger and draft skeleton
- [ ] Generate reviewed evidence-backed reports
- [ ] Add contradictory-evidence searches

## Review, security, and operations

- [x] Implement deterministic local citation-integrity validation and persisted findings
- [ ] Implement independent semantic fact-checking and release-blocking citation gates
- [ ] Add critical review and prompt-injection checks
- [ ] Replace development-header identity with production Entra authentication and role mapping
- [ ] Complete approval and release workflows
- [ ] Add Cosmos DB, Blob Storage, Service Bus, and Key Vault deployment
- [ ] Add monitoring, audit events, and production deployment

## Remaining quality and integration work

- [ ] Integrate the newer master and `feature/research-quality-evals` work into this checkout without losing local changes.
- [ ] Expand and run the retrieval evaluation gold set; measure relevance, date accuracy, provider failures, duplicates, source independence, and contradiction discovery.
- [ ] Expand and run model/review evaluations for unsupported claims, conflicts, stale evidence, prompt injection, and failure recovery; define release-blocking thresholds.
- [ ] Complete governed licensed full-text retrieval, including licence metadata, source provenance, coverage tests, and abstract-versus-full-text comparisons.
- [ ] Run the guarded live Playwright flow with real scholarly providers and the selected remote model; retain redacted evidence and confirm it stops before approval or release.
- [ ] Deploy and validate the hosted Foundry agent, if selected, including identity, endpoint access, budget, and browser-level behavior.
- [ ] Replace SQLite and the local worker with production Cosmos/Blob/Search/Service Bus adapters; add hosting, secrets, telemetry, backup/restore, and rollback procedures.
- [ ] Verify the latest hosted CI checks after branch integration.

## Audit follow-up backlog (2026-09-12)

Acceptance criteria and parent task mappings: [Hardening backlog](docs/HARDENING_BACKLOG.md).

- [x] HARD-001 (P0): Harden document fetching with redirect/address validation and streaming download limits.
- [x] HARD-002 (P1): Report provider failures and partial results explicitly.
- [x] HARD-003 (P1): Fix arXiv date-filtered recency retrieval and bounded pagination.
- [x] HARD-004 (P1): Enforce snapshot immutability with atomic persistence and retry tests.
- [x] HARD-005 (P1): Add research-system Python and Playwright CI workflow (hosted run pending push).
- [x] HARD-006 (P2): Refresh Azure plan and completion labels against verified code.

## Definition of done for the next release

- A confirmed research run discovers real sources.
- Sources are normalized, stored, and searchable locally.
- Search results include stable citations and source metadata.
- The workflow is covered by automated API and end-to-end tests.
