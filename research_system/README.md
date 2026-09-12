# Multi-Agent Research System

## Overview

This is an early implementation of the multi-agent research plan. The local vertical slice persists projects and runs in SQLite, uses local auth headers for tenant/user scope, generates and stores a bounded research plan, requires scope confirmation before queueing, and can discover/search paper metadata through OpenAlex, Crossref, and arXiv. The planner can run deterministically offline or call an Azure model with Microsoft Entra authentication.

### Current implementation status

- Working: health/OpenAPI, local project and run persistence, local auth headers and project membership checks, planner agent, legal run-state checks, scope confirmation, OpenAlex/Crossref/arXiv paper discovery with cross-provider deduplication, source snapshots, passage records, local evidence ingestion/search, deterministic draft skeleton, claim ledger, provider status, and guarded 401/403/404/409/502 errors.
- Azure-verified: direct `gpt-5.6-sol` planner inference through `DefaultAzureCredential`; no Azure API key is stored.
- Still scaffolded: crawling, Blob Storage, AI Search, Cosmos DB, Service Bus, LLM synthesis/review agents, production Entra authorization, and the production release protocol.
- The release endpoint returns `501 Not Implemented` until verified artifacts, authenticated approval, and conditional commit exist; this prototype never claims a report was published.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Researcher (User)                          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │   FastAPI REST API   │
            └──────────┬───────────┘
                       │
         ┌─────────────┼─────────────┐
         │             │             │
         ▼             ▼             ▼
    ┌─────────┐  ┌─────────┐  ┌──────────┐
    │Planner  │  │Research │  │Synthesis │
    │Agent    │  │Agent    │  │Agent     │
    └─────────┘  └─────────┘  └──────────┘
         │             │             │
         └─────────────┼─────────────┘
                       │
         ┌─────────────┼─────────────┬──────────────────┐
         │             │             │                  │
         ▼             ▼             ▼                  ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐  ┌────────────────┐
    │Fact      │ │Critical  │ │Citation  │  │Evaluation Gate │
    │Checker   │ │Reviewer  │ │Validator │  │& Orchestrator  │
    └──────────┘ └──────────┘ └──────────┘  └────────────────┘
         │             │             │                  │
         └─────────────┼─────────────┴──────────────────┘
                       │
              ┌────────▼────────┐
              │  Human Approval │
              │  & Adjudication │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │ Release & Audit │
              │ Internal Publish│
              └─────────────────┘
```

## Core Components

### 1. **Data Models** (`src/models.py`)
- Pydantic models for all core entities
- Enums for state management and validation
- Compliance with specification data contracts

**Key Models:**
- `RunRecord` - Orchestration state for research runs
- `EvidenceRecord` - Source passages and metadata
- `ClaimRecord` - Factual assertions in reports
- `ReviewFinding` - Fact-checking and review results
- `ApprovalRecord` - Human approval tracking
- `ReleaseRecord` - Published internal reports

### 2. **Database Layer** (`src/database.py`)
- Cosmos DB document models
- Project isolation and authorization guards
- Audit trail records
- Outbox pattern for Service Bus integration

**Key Records:**
- `ProjectGuardRecord` - Tenant/project scope enforcement
- `RunControlRecord` - Run orchestration state
- `AuditRecord` - Operation audit trail
- `OutboxRecord` - Event publishing queue

### 3. **Configuration** (`src/config.py`)
- Pydantic Settings for all Azure services
- LLM and embedding model configuration
- Research execution parameters
- API and security settings
- Environment variable management

### 4. **Services** (`src/services.py`)
- Business logic layer
- Authorization and scope enforcement
- Cosmos DB operations
- Azure Blob Storage integration
- Azure AI Search orchestration

**Key Services:**
- `ProjectService` - Project and membership management
- `ResearchRunService` - Run lifecycle management
- `ApprovalService` - Approval workflow
- `ReleaseService` - Publication and withdrawal (ADR-015)
- `EvidenceService` - Search and retrieval

### 5. **Agent Framework** (`src/agents.py`)
- Base `Agent` abstract class
- Concrete agent implementations
- Agent message protocol
- Orchestrator state machine

**Implemented Agents:**
- `PlannerAgent` - Decomposes research questions
- `SourceSearcherAgent` - Discovers sources
- `IngestionAgent` - Extracts passages
- `ResearchAgent` - Retrieves evidence
- `SynthesisAgent` - Generates report draft
- `FactCheckerAgent` - Verifies claims
- `CriticalReviewerAgent` - Reviews methodology

### 6. **API Layer** (`src/main.py`)
- FastAPI application with full OpenAPI documentation
- RESTful endpoints for all major operations
- CORS middleware and error handling
- Application lifecycle management

**Endpoint Categories:**
- Health and system info
- Project management
- Research run lifecycle
- Approval and release workflows
- Evidence search and retrieval

## API Endpoints

### Health & System
- `GET /health` - Health check
- `GET /api/v1/system/info` - System information
- `GET /api/v1/ai/status` - Selected model provider (does not call the model)

### Projects
- `POST /api/v1/projects` - Create project
- `GET /api/v1/projects/{project_id}` - Get project details

### Research Runs
- `POST /api/v1/projects/{project_id}/runs` - Create research run
- `GET /api/v1/projects/{project_id}/runs/{run_id}` - Get run status
- `POST /api/v1/projects/{project_id}/runs/{run_id}/plan` - Generate and persist a research plan
- `POST /api/v1/projects/{project_id}/runs/{run_id}/confirm-scope` - Confirm research scope
- `POST /api/v1/projects/{project_id}/runs/{run_id}/execute-local` - Discover and ingest local/OpenAlex evidence
- `POST /api/v1/projects/{project_id}/runs/{run_id}/synthesize-local` - Create a local cited draft skeleton and claim ledger
- `POST /api/v1/projects/{project_id}/runs/{run_id}/validate-citations-local` - Check local claim/citation integrity and persist findings
- `POST /api/v1/projects/{project_id}/runs/{run_id}/cancel` - Cancel run

### Approvals & Release
- `POST /api/v1/projects/{project_id}/runs/{run_id}/request-approval` - Request approval
- `POST /api/v1/projects/{project_id}/runs/{run_id}/release` - Release report
- `POST /api/v1/releases/{release_id}/withdraw` - Withdraw release

### Evidence & Search
- `POST /api/v1/projects/{project_id}/runs/{run_id}/search` - Search evidence
- `GET /api/v1/projects/{project_id}/evidence/{evidence_id}` - Get evidence details

## Setup and Deployment

### Local Development

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Run the offline local mode:**
```powershell
.\run_local.ps1
```

The API is available at `http://127.0.0.1:8000`; Swagger is at `/docs`. This mode uses SQLite and a deterministic planner, so it does not send data or incur model usage.

Local API calls require these headers:

```http
X-Tenant-Id: TEN-DEMO
X-User-Id: local-user
```

The old `tenant_id` query parameter is deprecated; if supplied, it must match `X-Tenant-Id`.

To discover real research papers through the scholarly providers while keeping the planner mocked:

```powershell
.\run_local.ps1 -SourceConnector scholarly_with_local_fallback
```

Use Swagger in this sequence:

1. `POST /api/v1/projects`
2. `POST /api/v1/projects/{project_id}/runs`
3. `POST /api/v1/projects/{project_id}/runs/{run_id}/plan`
4. `POST /api/v1/projects/{project_id}/runs/{run_id}/confirm-scope`
5. `POST /api/v1/projects/{project_id}/runs/{run_id}/execute-local`
6. `POST /api/v1/projects/{project_id}/runs/{run_id}/synthesize-local`
7. `POST /api/v1/projects/{project_id}/runs/{run_id}/validate-citations-local`
8. `POST /api/v1/projects/{project_id}/runs/{run_id}/search`

Connector choices are `local` (the deterministic default), `openalex`, `crossref`, `arxiv`, `scholarly_with_local_fallback`, and the backward-compatible `openalex_with_local_fallback`. For questions like `What is the latest on AI?`, OpenAlex and Crossref search recent works newest-first unless you provide an explicit date range on the run. Scholarly aggregation deduplicates shared DOI, arXiv, OpenAlex, and canonical identifiers. Before persistence, source URLs are checked against each run's approved/excluded domains and explicit licenses are checked against the configured extraction policy. External requests use bounded retries with exponential backoff and jitter; arXiv defaults to one request every three seconds.

The default execution path ingests provider abstracts without document network I/O. Call `EvidenceService.ingest_full_sources(...)` explicitly when a run has approved domains and licenses: it safely fetches an identified PDF or HTML URL, enforces content-size/type limits, extracts normalized text, chunks it into bounded passages, removes duplicate chunks by SHA-256, and stores the resulting source snapshots and passages in SQLite.
`synthesize-local` creates a draft skeleton and claim ledger for review. `validate-citations-local` checks that each claim resolves to eligible evidence from the same run/revision and that deterministic draft text occurs in the cited passage. It does not perform semantic fact-checking, critical review, approval, or release.
Cancelled or terminal runs cannot be confirmed or executed again; create a new run for a retry.

### Azure model inference from the local API

Sign in with `az login`, then run:

```powershell
.\run_azure.ps1
```

The launcher uses the existing `gpt-5.6-sol` default for this checkout. Override it when needed:

```powershell
.\run_azure.ps1 -Endpoint 'https://your-resource.openai.azure.com' -Deployment 'your-deployment' -Port 8010
```

Locally, `DefaultAzureCredential` uses the Azure CLI session. In Azure hosting it can use managed identity. The model-backed operation is `POST /api/v1/projects/{project_id}/runs/{run_id}/plan`.

You can combine Azure planning with OpenAlex discovery:

```powershell
.\run_azure.ps1 -SourceConnector openalex_with_local_fallback
```

### Docker Deployment

1. **Build image:**
```bash
docker build -t research-system:latest .
```

2. **Run container:**
```bash
docker run -p 8000:8000 \
  --env-file .env \
  research-system:latest
```

### Azure hosting

Azure infrastructure and application hosting are not implemented in this checkout yet. The direct model connection above is a local development path, not a deployed production service.

## Key Design Decisions

### ADR-001: Deterministic Orchestration
- State machine-driven, not free-form conversation
- Validated JSON contracts between agents
- Replay and recovery capabilities

### ADR-002: Retrieval Before Generation
- LLM knowledge used only for planning
- All claims grounded in indexed sources
- Material claims require evidence citations

### ADR-012: Project Isolation
- Tenant and project scope enforced at every boundary
- No cross-project shared indices or caches
- Reauthorization on every access

### ADR-015: Cross-Service Release Protocol
- Conditional writes with ETag checks
- Atomic Cosmos DB transactions
- Durable outbox pattern for Service Bus
- Handles race conditions and failures

### ADR-017: Complete User Journeys
- Visible outcomes for all paths (success, insufficient evidence, cancellation, etc.)
- User confirmation required before execution
- Audit trail for all operations

## Testing

Run tests:
```bash
pytest tests/
```

Run with coverage:
```bash
pytest --cov=src tests/
```

Install Chromium once and run the browser/API journey:

```powershell
npm install
npx playwright install chromium
npm run test:e2e
```

## Security Considerations

1. **Implemented for model access**: Microsoft Entra tokens via `DefaultAzureCredential`; no Azure API key is stored.
2. **Local-only boundary**: local development uses `X-Tenant-Id` and `X-User-Id` headers; production Entra authorization is not implemented.
3. **Planned controls**: managed identity, Cosmos isolation, Key Vault, private networking, source-policy enforcement, and complete audit records remain future work.

## Next Steps for Implementation

### Phase 1: Core Infrastructure
- [ ] Cosmos DB schema and container setup
- [ ] Azure Blob Storage configuration
- [ ] Azure AI Search index creation
- [ ] Service Bus queue setup
- [ ] Application Insights integration

### Phase 2: Agent Implementation
- [ ] LLM integration for Planner and Synthesis agents
- [x] OpenAlex connector
- [x] Local source snapshots, passage records, draft skeleton, and claim ledger
- [x] Crossref and arXiv connectors
- [ ] Web crawler with robots.txt compliance
- [ ] PDF and HTML extraction
- [ ] Passage-level citation tracking

### Phase 3: Search and Retrieval
- [ ] Embedding generation pipeline
- [ ] Hybrid search implementation (keyword + semantic + vector)
- [ ] Query expansion and relevance ranking
- [ ] Search evaluation metrics

### Phase 4: Review Pipeline
- [ ] Fact-checker agent implementation
- [ ] Critical reviewer agent implementation
- [ ] Citation validator implementation
- [ ] Quality gate evaluation

### Phase 5: Release Workflow
- [ ] Release artifact preparation
- [ ] ADR-015 protocol implementation
- [ ] Approval workflow UI
- [ ] Release withdrawal and audit

### Phase 6: Operations & Monitoring
- [ ] OpenTelemetry instrumentation
- [ ] Cost tracking and budget enforcement
- [ ] Failure recovery procedures
- [ ] Migration and versioning support

## Configuration Reference

See `.env.example` for all configurable parameters:
- Azure service endpoints and credentials
- LLM model selection and parameters
- Search and retrieval settings
- Research execution limits
- Approval and release policies
- API and CORS configuration

## Documentation

- `SPECIFICATION.md` - Complete system specification
- `RESEARCH.md` - Research workflow and evidence handling
- `ARCHITECTURE.md` - Detailed architecture and design decisions
- `API.md` - Complete API reference

## License

[Your License Here]

## Contributing

[Contributing Guidelines]
