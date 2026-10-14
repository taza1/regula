# Project Roadmap

## Current status (2026-10-11)

- The dashboard and durable local execution queue are implemented and verified in the current branch.
- Quality hardening is implemented on `feature/research-quality-hardening`. Verification: `python -m pytest tests -q` -> 71 passed; `npm run test:e2e` -> 4 passed, 1 opt-in live test skipped; the guarded live test passed separately. Live scholarly retrieval passed both configured cases. The three-repeat Azure model suite passed all seven cases on every repeat after bounded backoff and bias phrase matching were added. A real Crossref CC BY full-text extraction and abstract comparison also completed.
- The guarded live browser flow passed with scholarly providers and Azure `gpt-5.6-sol`; it completed at `adjudication_required` with 8 real-source evidence records and 7 reviewed claims. A redacted summary is retained in the local temp directory; no approval or release was created.
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
- [x] Add bounded counter-evidence queries for null/no-effect/failed-replication findings; source records retain the discovery query type.

## Review, security, and operations

- [x] Implement deterministic local citation-integrity validation and persisted findings
- [x] Implement semantic fact-checking, critical review, prompt-injection checks, and release-blocking review gates (same configured model; independent model verification remains open)
- [x] Add authenticated API identity and role enforcement (browser SSO remains open)
- [x] Complete local approval and release workflows (production release remains disabled by default)
- [ ] Add Cosmos DB, Blob Storage, Service Bus, and Key Vault deployment
- [ ] Add monitoring, audit events, and production deployment

## Remaining quality and production work

- [x] Expand retrieval evaluations and define release thresholds: Precision@K >= 0.60, Recall@K >= 0.80 against non-empty DOI gold sets, date accuracy >= 0.90, duplicate leakage <= 0.10, at most one failed provider of three when aggregate results remain, explicit author/source independence groups, and required contradiction discovery. The latest live scholarly run passed both cases; all three providers responded, with zero duplicate leakage after deduplication.
- [x] Expand and run repeated model/review evaluations for unsupported claims, entailment, selection bias, prompt injection, stale evidence, conflicts, and transient-failure recovery. Azure `gpt-5.6-sol` passed all seven cases in each of three repeats; transient-failure recovery passed in every repeat. Release blocks on any failed case.
- [x] Tighten governed full-text retrieval: only explicit allowlisted CC BY/CC0 identifiers or recognized licence URLs are accepted; ambiguous labels such as “open access” and “arxiv” are rejected. Snapshots/evidence preserve licence, fetched URL, MIME type, retrieval time, and content hash; abstract/full-text coverage and added-term comparison metrics are implemented and locally tested.
- [x] Run the guarded live Playwright workflow with OpenAlex, Crossref, arXiv, and Azure `gpt-5.6-sol`. It passed and stopped at `adjudication_required`; no approval/release occurred. Redacted summary: `%TEMP%\regula-live-e2e-redacted.json`.
- [x] Run a real-source full-text extraction against a provider-declared, allowlisted licence and record its abstract-only comparison. Crossref declared CC BY 4.0 for a Research Square HTML source; extraction retained licence, URL, MIME type, retrieval time, and hash. One-source abstract/full-text coverage was 100%; the extracted passage added zero unique terms to the abstract vocabulary. Redacted summary: `%TEMP%\regula-fulltext-live-redacted.json`.
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
