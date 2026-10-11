# Project Roadmap

## Current status (2026-10-11)

- The dashboard and durable local execution queue are implemented and verified in the current branch.
- Local verification: `python -m pytest tests -q` -> 66 passed; `npm run test:e2e` -> 4 passed, 1 live Foundry test skipped because remote credentials were not configured.
- Dashboard browser coverage exercises project creation, planning, execution, and draft/evidence inspection. A successful local run stops in `reviewing`; human review remains required.
- The newer task breakdown is on `feature/research-quality-evals` at `45bea89`; its detailed task documents are not yet integrated here.
- See [Project completion plan](docs/PROJECT_COMPLETION_PLAN.md) and [review/release status](docs/REVIEW_RELEASE_STATUS.md) for production boundaries and delivery steps.

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
- [x] Implement background run workers
- [x] Add research workspace dashboard and durable execution queue
- [x] Generate deterministic local claim ledger and draft skeleton
- [x] Generate evidence-backed drafts with semantic fact-check and critical review gates (local prototype; model review still needs evaluation)
- [ ] Add contradictory-evidence searches

## Review, security, and operations

- [x] Implement deterministic local citation-integrity validation and persisted findings
- [x] Implement semantic fact-checking, critical review, prompt-injection checks, and release-blocking review gates (same configured model; independent model verification remains open)
- [x] Add authenticated API identity and role enforcement (browser SSO remains open)
- [x] Complete local approval and release workflows (production release remains disabled by default)
- [ ] Add Cosmos DB, Blob Storage, Service Bus, and Key Vault deployment
- [ ] Add monitoring, audit events, and production deployment

## Remaining quality and production work

- [ ] Expand and run retrieval evaluations for relevance, date handling, provider outages, duplicates, source independence, and contradictory evidence; set held-out acceptance thresholds.
- [ ] Expand and run model/review evaluations for unsupported claims, conflicts, stale sources, prompt injection, and failure recovery; include repeated runs and release-blocking criteria.
- [ ] Complete governed full-text retrieval with licence evidence, provenance, coverage checks, and abstract-versus-full-text comparisons.
- [ ] Run the guarded live Playwright workflow with real scholarly providers and the selected remote model; retain redacted evidence and verify it stops before approval/release.
- [ ] Deploy and validate the hosted Foundry agent if selected, including identity, endpoint access, cost limits, and browser-level behavior.
- [ ] Replace local SQLite persistence and workers with production Cosmos/Blob/Search/Service Bus adapters; add API hosting, secret delivery, monitoring, backup/restore, and rollback.

## Audit follow-up backlog (2026-09-12)

Acceptance criteria and parent task mappings: [Hardening backlog](docs/HARDENING_BACKLOG.md).

- [x] HARD-001 (P0): Harden document fetching with redirect/address validation and streaming download limits.
- [x] HARD-002 (P1): Report provider failures and partial results explicitly.
- [x] HARD-003 (P1): Fix arXiv date-filtered recency retrieval and bounded pagination.
- [x] HARD-004 (P1): Enforce snapshot immutability with atomic persistence and retry tests.
- [x] HARD-005 (P1): Add research-system Python and Playwright CI workflow; verify the hosted PR run.
- [x] HARD-006 (P2): Refresh Azure plan and completion labels against verified code.

## Definition of done for the next release

- A confirmed research run discovers real sources.
- Sources are normalized, stored, and searchable locally.
- Search results include stable citations and source metadata.
- The workflow is covered by automated API and end-to-end tests.
