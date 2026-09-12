# Project Roadmap

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

- [ ] Add SQLite full-text search
- [ ] Add embeddings and vector retrieval
- [ ] Add Azure AI Search adapter
- [ ] Implement background run workers
- [x] Generate deterministic local claim ledger and draft skeleton
- [ ] Generate reviewed evidence-backed reports
- [ ] Add contradictory-evidence searches

## Review, security, and operations

- [ ] Implement fact-checking and citation validation
- [ ] Add critical review and prompt-injection checks
- [ ] Add authenticated identity and role enforcement
- [ ] Complete approval and release workflows
- [ ] Add Cosmos DB, Blob Storage, Service Bus, and Key Vault deployment
- [ ] Add monitoring, audit events, and production deployment

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
