# Project Flow

## Current end-to-end flow

```mermaid
flowchart TD
    A[Create project] --> B[Create research run]
    B --> C[Generate research plan]
    C --> D[Mock AI or Azure AI planner]
    D --> E[Review subquestions and search queries]
    E --> F[Confirm scope]
    F --> G[Run becomes queued]
    G --> H[Discover local fixtures or OpenAlex works]
    H --> I[Validate tenant, project, and run scope]
    I --> J[Persist source records in SQLite]
    J --> K[Ingest abstracts/passages as evidence]
    K --> L[Search evidence]
    L --> M[Rank matching paper passages]
    M --> N[Retrieve evidence by ID]
```

## API sequence

1. `POST /api/v1/projects`
2. `POST /api/v1/projects/{project_id}/runs`
3. `POST /api/v1/projects/{project_id}/runs/{run_id}/plan`
4. `POST /api/v1/projects/{project_id}/runs/{run_id}/confirm-scope`
5. `POST /api/v1/projects/{project_id}/runs/{run_id}/execute-local`
6. `POST /api/v1/projects/{project_id}/runs/{run_id}/evidence`
7. `POST /api/v1/projects/{project_id}/runs/{run_id}/search`
8. `GET /api/v1/projects/{project_id}/evidence/{evidence_id}`

## Current boundaries

The local vertical slice is functional through source discovery, evidence
ingestion, indexing, and keyword search. By default `execute-local` uses
deterministic local fixtures and makes no external network calls. Set
`SOURCE_CONNECTOR=openalex` or launch with
`.\run_local.ps1 -SourceConnector openalex_with_local_fallback` to discover real
OpenAlex paper metadata and ingest available abstracts as evidence.

Crossref, arXiv, governed crawling, background workers, report synthesis, and
production Azure storage/search integrations are not yet connected.
