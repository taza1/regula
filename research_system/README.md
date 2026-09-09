# Multi-Agent Research System

## Overview

This is the foundational implementation of a comprehensive multi-agent research platform following the specification in `SPECIFICATION.md`. The system orchestrates multiple AI agents to conduct research, fact-check findings, and publish vetted reports with full audit trails.

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

### Projects
- `POST /api/v1/projects` - Create project
- `GET /api/v1/projects/{project_id}` - Get project details

### Research Runs
- `POST /api/v1/projects/{project_id}/runs` - Create research run
- `GET /api/v1/projects/{project_id}/runs/{run_id}` - Get run status
- `POST /api/v1/projects/{project_id}/runs/{run_id}/confirm-scope` - Confirm research scope
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

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your Azure credentials and settings
```

3. **Run development server:**
```bash
python run.py
```

The API will be available at `http://localhost:8000` with docs at `/docs`.

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

### Azure Deployment

1. **Create Azure resources using Bicep:**
```bash
az deployment group create \
  --resource-group my-rg \
  --template-file infra/main.bicep \
  --parameters parameters.json
```

2. **Deploy to Container Instances or App Service:**
```bash
az container create \
  --resource-group my-rg \
  --name research-system \
  --image research-system:latest \
  --ports 8000 \
  --environment-variables-from-file env.list
```

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

## Security Considerations

1. **Authentication**: Uses Azure AD and managed identities
2. **Authorization**: Project-scoped role-based access control
3. **Data Isolation**: Tenant and project boundaries enforced
4. **Source Handling**: Retrieved documents treated as untrusted
5. **Secrets Management**: Azure Key Vault for external API credentials
6. **Audit Trail**: Complete operation history with actor information

## Next Steps for Implementation

### Phase 1: Core Infrastructure
- [ ] Cosmos DB schema and container setup
- [ ] Azure Blob Storage configuration
- [ ] Azure AI Search index creation
- [ ] Service Bus queue setup
- [ ] Application Insights integration

### Phase 2: Agent Implementation
- [ ] LLM integration for Planner and Synthesis agents
- [ ] OpenAlex, Crossref, arXiv connectors
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
