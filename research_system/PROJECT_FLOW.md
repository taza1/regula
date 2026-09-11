# Project Flow

## Current end-to-end flow

```mermaid
flowchart TD
    A[Read X-Tenant-Id and X-User-Id headers] --> B[Create project and membership]
    B --> C[Create research run]
    C --> D[Generate research plan]
    D --> E[Mock AI or Azure AI planner]
    E --> F[Review subquestions and search queries]
    F --> G[Confirm scope]
    G --> H[Run becomes queued]
    H --> I[Discover local fixtures or OpenAlex works]
    I --> J[Validate tenant, project, role, and run state]
    J --> K[Persist source records in SQLite]
    K --> L[Ingest abstracts/passages as evidence]
    L --> M[Search evidence]
    M --> N[Rank matching paper passages]
    N --> O[Retrieve evidence by ID]
```

## API sequence

Send `X-Tenant-Id` and `X-User-Id` headers with project/run/evidence requests.
The deprecated `tenant_id` query parameter is only accepted when it matches
`X-Tenant-Id`.

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
ingestion, indexing, keyword search, local project membership checks, and legal
run-state transitions. By default `execute-local` uses
deterministic local fixtures and makes no external network calls. Set
`SOURCE_CONNECTOR=openalex` or launch with
`.\run_local.ps1 -SourceConnector openalex_with_local_fallback` to discover real
OpenAlex paper metadata and ingest available abstracts as evidence.
Cancelled and terminal runs cannot be revived by a later confirmation or worker
call.

Crossref, arXiv, governed crawling, background workers, report synthesis, and
production Azure storage/search integrations are not yet connected.
