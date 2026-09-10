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
    G --> H[Index evidence passage]
    H --> I[Validate tenant, project, and run scope]
    I --> J[Persist evidence in SQLite]
    J --> K[Search evidence]
    K --> L[Rank matching passages]
    L --> M[Retrieve evidence by ID]
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

The local vertical slice is functional through offline source discovery, evidence
ingestion, indexing, and keyword search. `execute-local` uses deterministic local
fixtures and makes no external network calls.
External source discovery, background workers, report synthesis, and production Azure
storage/search integrations are not yet connected.
