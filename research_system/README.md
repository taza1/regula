# Multi-Agent Research System

For the latest implementation and production boundaries, see [Review and release status](docs/REVIEW_RELEASE_STATUS.md).

## Overview

This is an early implementation of the multi-agent research plan. The local vertical slice persists projects and runs in SQLite, uses local auth headers for tenant/user scope, generates and stores a bounded research plan, requires scope confirmation before queueing, and can discover/search paper metadata through OpenAlex, Crossref, and arXiv. The planner can run deterministically offline or call an Azure model with Microsoft Entra authentication.

### Current implementation status

- Working locally: health/OpenAPI, dashboard, SQLite project/run persistence, local auth headers, project membership checks, planner, legal run-state checks, scope confirmation, background execution, OpenAlex/Crossref/arXiv discovery, source snapshots, passage records, local evidence ingestion/search, model-backed synthesis, semantic fact-checking, critical review, claim ledger, provider status, and guarded 401/403/404/409/502 errors.
- Azure/AI Foundry verified locally: direct `gpt-5.6-sol` calls through `DefaultAzureCredential`; no Azure API key is stored. The local Azure launcher uses real scholarly sources by default through the `scholarly` connector.
- Source hardening: live Azure/Playwright testing verified real Crossref/OpenAlex source records, no local synthetic fallback, no placeholder abstracts as evidence, provider-specific query cleanup, deterministic relevance reranking, and budget spread across planner queries.
- Licensed full text is opt-in per run. It uses provider-advertised document URLs, requires an explicit recognized licence plus an approved domain, and stores bounded HTML/PDF passages with content hashes.
- Remote synthesis, semantic fact-checking and critical review are implemented with strict output contracts and approval gates. Entra API token validation and transactional local release are opt-in.
- Production gaps: deployed Azure adapters for Cosmos/Blob/Search/Service Bus, hosted API/SSO, production observability, live hosted-agent deployment verification, retrieval quality evaluation, and report publication governance.
- Release remains disabled by default (`501`). With `ENABLE_REPORT_RELEASE=true`, passing model review, exact-content human approval and a separate publisher can create an authenticated local release artifact. This does not deploy or publish to Azure.

## Quick Start

Use Python 3.11+ from `research_system`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run the deterministic local app:

```powershell
.\run_local.ps1 -Port 8000
```

Open the dashboard:

```text
http://127.0.0.1:8000/dashboard
```

This mode uses `MODEL_PROVIDER=mock`, local SQLite at `data/research_system.db`, and local source fixtures. It does not call Azure or incur model usage.

For real scholarly metadata while keeping the model mocked:

```powershell
.\run_local.ps1 -Port 8000 -SourceConnector scholarly
```

Run the Azure/AI Foundry-backed local app:

```powershell
az login
.\run_azure.ps1 -Endpoint 'https://your-resource.openai.azure.com' -Deployment 'gpt-5.6-sol' -Port 8015
```

Open:

```text
http://127.0.0.1:8015/dashboard
```

The Azure launcher sets `MODEL_PROVIDER=azure`, uses Entra via `DefaultAzureCredential`, and defaults to `SOURCE_CONNECTOR=scholarly` so discovery uses OpenAlex, Crossref, and arXiv without local synthetic fallback.

Recommended dashboard flow:

1. Create a project.
2. Create a run with title, question, scope, date range, and max sources.
3. Generate the plan.
4. Confirm scope and execute.
5. Wait for background execution to finish.
6. Review evidence, draft, model review, blockers, and approval controls.

Run tests:

```powershell
$env:PYTHONPATH = (Get-Location).Path
pytest -q
```

Optional browser tests:

```powershell
npm install
npx playwright install chromium
npm run test:e2e
```

Run the opt-in live retrieval quality fixtures:

```powershell
$env:SOURCE_CONNECTOR = 'scholarly'
python scripts\run_quality_evals.py --suite retrieval --output data\retrieval-eval.json
```

The model fixtures and full live Playwright flow make remote model calls. See [docs/LIVE_INTEGRATION_SMOKE.md](docs/LIVE_INTEGRATION_SMOKE.md) for the guarded commands.

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
.\run_local.ps1 -SourceConnector scholarly
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

Connector choices are `local` (the deterministic default), `openalex`, `crossref`, `arxiv`, `scholarly`, `scholarly_with_local_fallback`, and the backward-compatible `openalex_with_local_fallback`. Use `scholarly` for live research checks because it does not fall back to synthetic local sources. For questions like `What is the latest on AI?`, OpenAlex and Crossref search recent works newest-first unless you provide an explicit date range on the run. Explicit date ranges keep relevance-biased ranking. Scholarly aggregation deduplicates shared DOI, arXiv, OpenAlex, and canonical identifiers. Before persistence, source URLs are checked against each run's approved/excluded domains and explicit licenses are checked against the configured extraction policy. External requests use bounded retries with exponential backoff and jitter; arXiv defaults to one request every three seconds.

The default execution path ingests provider abstracts without document network I/O. Call `EvidenceService.ingest_full_sources(...)` explicitly when a run has approved domains and licenses: it safely fetches an identified PDF or HTML URL, enforces content-size/type limits, extracts normalized text, chunks it into bounded passages, removes duplicate chunks by SHA-256, and stores the resulting source snapshots and passages in SQLite.
`synthesize-local` creates a draft skeleton and claim ledger for review. `validate-citations-local` checks that each claim resolves to eligible evidence from the same run/revision and that deterministic draft text occurs in the cited passage. It does not perform semantic fact-checking, critical review, approval, or release.
Cancelled or terminal runs cannot be confirmed or executed again; create a new run for a retry.

### Azure model inference from the local API

Sign in with `az login`, then run:

```powershell
.\run_azure.ps1 -Endpoint 'https://your-resource.openai.azure.com' -Deployment 'gpt-5.6-sol'
```

The launcher defaults to deployment `gpt-5.6-sol` and source connector `scholarly`. It requires either `-Endpoint` or `AZURE_OPENAI_ENDPOINT`:

```powershell
.\run_azure.ps1 -Endpoint 'https://your-resource.openai.azure.com' -Deployment 'your-deployment' -Port 8010
```

Locally, `DefaultAzureCredential` uses the Azure CLI session. In Azure hosting it can use managed identity. The dashboard flow calls the model during planning and, when executed with a remote provider, during synthesis, fact-checking, and critical review.

You can override the source connector when needed:

```powershell
.\run_azure.ps1 -Endpoint 'https://your-resource.openai.azure.com' -SourceConnector openalex
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

## Remaining Work and Improvements

### Before production
- [ ] Deploy and verify Azure infrastructure: Cosmos DB, Blob Storage, Azure AI Search, Service Bus, Key Vault, managed identities, private networking, monitoring, and backups.
- [ ] Replace local SQLite/queue/runtime adapters with Cosmos transactional state, immutable Blob artifacts, Service Bus workers/outbox delivery, and Azure AI Search indexing.
- [ ] Deploy and verify the Foundry hosted agent package, including identity, endpoint authorization, private DNS, egress, model access, and redacted telemetry.
- [ ] Add production API hosting and browser Entra sign-in. Local `X-Tenant-Id` and `X-User-Id` headers are development-only.
- [ ] Add deployment pipelines, rollback automation, smoke tests, backup/restore exercises, and operational runbooks.

### Research quality
- [x] Add opt-in licensed full-text retrieval beyond abstracts, with source-license/domain policy controls.
- [x] Add repeatable retrieval evaluation fixtures for relevance, recall, contradiction coverage, source independence, and temporal coverage.
- [x] Improve provider-specific query translation and local reranking; continue tuning negative/null-result recall using evaluation results.
- [ ] Add semantic/vector retrieval and measured precision/recall before relying on Azure AI Search ranking.
- [x] Add runnable model eval fixtures for entailment, unsupported claims, bias, prompt injection, and stale/conflicting evidence.
- [ ] Expand model and retrieval fixtures with adjudicated domain-specific gold sets and regression thresholds.

### Release governance
- [x] Model-driven synthesis, semantic fact-checking, critical review, approval gates, and local release artifact transaction.
- [x] Dashboard review status plus approval/release controls.
- [ ] Production release storage, withdrawal, audit export, and outbox delivery.
- [ ] Human reviewer workflow for adjudication when model review blocks a report.
- [ ] Policy decisions for who can approve, publish, withdraw, and externally share reports.

### Developer experience
- [x] Keep a documented Playwright live Azure/Foundry source-audit test as an opt-in, non-CI smoke test.
- [ ] Add a sample `.env.local.example` for common local Azure settings without resource-specific values.
- [ ] Add troubleshooting docs for Azure CLI auth, missing deployment names, source-provider rate limits, and failed model review.

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
