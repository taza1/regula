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
- [x] Add Python and Playwright test coverage
- [x] Add local and Azure launcher scripts

## Next milestone: real source discovery

- [x] Add OpenAlex connector
- [ ] Add Crossref connector
- [ ] Add arXiv connector
- [ ] Normalize source metadata and identifiers
- [ ] Enforce approved and excluded domain policies
- [ ] Add retries, rate limits, and source attribution

## Evidence pipeline

- [ ] Download HTML and PDF documents
- [ ] Extract clean text and passages
- [ ] Calculate content hashes and detect duplicates
- [ ] Store source metadata and raw artifacts
- [ ] Add passage-level metadata and citation references

## Search and research generation

- [ ] Add SQLite full-text search
- [ ] Add embeddings and vector retrieval
- [ ] Add Azure AI Search adapter
- [ ] Implement background run workers
- [ ] Generate evidence-backed claims and reports
- [ ] Add contradictory-evidence searches

## Review, security, and operations

- [ ] Implement fact-checking and citation validation
- [ ] Add critical review and prompt-injection checks
- [ ] Add authenticated identity and role enforcement
- [ ] Complete approval and release workflows
- [ ] Add Cosmos DB, Blob Storage, Service Bus, and Key Vault deployment
- [ ] Add monitoring, audit events, and production deployment

## Definition of done for the next release

- A confirmed research run discovers real sources.
- Sources are normalized, stored, and searchable locally.
- Search results include stable citations and source metadata.
- The workflow is covered by automated API and end-to-end tests.
