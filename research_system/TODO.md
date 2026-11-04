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

- [x] Add SQLite full-text search (FTS5, BM25)
- [ ] Add embeddings and vector retrieval (local hashed-embedding baseline done; no learned model yet)
- [ ] Add Azure AI Search adapter
- [x] Implement background run workers (in-process queue, persisted job status)
- [x] Generate deterministic local claim ledger and draft skeleton
- [x] Generate reviewed evidence-backed reports (deterministic draft passes review gates; no model-written prose yet)
- [x] Add contradictory-evidence searches

## Review, security, and operations

- [x] Implement fact-checking and citation validation (rule-based, offline)
- [x] Add critical review and prompt-injection checks (rule-based, offline)
- [ ] Add authenticated identity and role enforcement (local project roles enforced on every endpoint; Entra ID token validation still needed)
- [x] Complete approval and release workflows (local file release; digest-bound approval)
- [ ] Add Cosmos DB, Blob Storage, Service Bus, and Key Vault deployment
- [ ] Add monitoring and production deployment (local hash-chained audit events done)

## Definition of done for the next release

- A confirmed research run discovers real sources.
- Sources are normalized, stored, and searchable locally.
- Search results include stable citations and source metadata.
- The workflow is covered by automated API and end-to-end tests.
