# Architecture: Multi-Agent Research System

## System Overview

The Multi-Agent Research System is a comprehensive platform for conducting evidence-based research with autonomous fact-checking, critical review, and human-approved publication. The system is built on deterministic multi-agent orchestration, project-scoped isolation, and invariant-preserving cross-service releases.

## Core Principles

1. **Deterministic Orchestration**: State machine-driven multi-agent execution, not free-form conversation
2. **Evidence-Based Claims**: All material claims grounded in indexed, retrievable sources
3. **Project Isolation**: Tenant and project boundaries enforced at every service boundary
4. **Audit Trails**: Complete operation history with actor, timestamp, and impact tracking
5. **Bounded Autonomy**: Agents cannot modify external systems; humans approve all releases
6. **Untrusted Source Handling**: Retrieved documents never treated as instructions or policy

## Layered Architecture

```
┌─────────────────────────────────────────────────────┐
│                  FastAPI REST API                   │
│                (Project, Run, Release, Search)      │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│                  Service Layer                      │
│      (Project, Run, Approval, Release, Evidence)    │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│            Agent Orchestrator                       │
│      (Planner, Research, Synthesis, Review)         │
└────────────────────┬────────────────────────────────┘
                     │
         ┌───────────┼───────────┬──────────────┐
         │           │           │              │
         ▼           ▼           ▼              ▼
    ┌────────┐  ┌────────┐  ┌────────┐   ┌──────────┐
    │Cosmos  │  │Blob    │  │AI      │   │Service   │
    │ DB     │  │Storage │  │Search  │   │Bus       │
    └────────┘  └────────┘  └────────┘   └──────────┘
```

## Data Flow

### Research Execution Pipeline

```
1. User Request
   ├─ Research title, question, scope
   ├─ Approved domains, date range
   └─ Budget and time limits
        ▼
2. Planner Agent
   ├─ Decompose question into subquestions
   ├─ Generate search queries
   └─ Define evidence criteria
        ▼
3. Source Discovery
   ├─ Query OpenAlex, Crossref, arXiv
   ├─ Governed web crawling
   └─ Candidate source collection
        ▼
4. Ingestion Pipeline
   ├─ Fetch documents (PDF, HTML)
   ├─ Extract passages with structure
   ├─ Compute content hashes
   └─ Store originals + indexed passages
        ▼
5. Research Agent
   ├─ Hybrid search (keyword + semantic + vector)
   ├─ Relevance ranking
   ├─ Filter by source quality and policy
   └─ Return ranked evidence set
        ▼
6. Synthesis Agent
   ├─ Generate draft report from evidence
   ├─ Create material claims with citations
   ├─ Link claims to passage IDs
   └─ Output draft + claim ledger
        ▼
7. Parallel Review
   ├─ Fact-Checker: Verify claims vs evidence
   ├─ Critical Reviewer: Assess methodology
   ├─ Citation Validator: Check DOIs, URLs
   └─ Safety Reviewer: Check policy compliance
        ▼
8. Evaluation Gate
   ├─ Check all findings status
   ├─ Identify critical issues
   ├─ Allow max 3 revisions
   └─ Decision: Pass, Revise, Adjudication
        ▼
9. Human Approval
   ├─ Review findings and limitations
   ├─ Approve or request changes
   ├─ Sign approval record
   └─ Approve report digest
        ▼
10. Release (ADR-015 Protocol)
    ├─ Freeze artifacts and compute digest
    ├─ Write blobs to Blob Storage
    ├─ Atomic Cosmos transaction
    ├─ Create release marker
    └─ Dispatch publication event
         ▼
11. Internal Publication
    ├─ Authenticated access only
    ├─ Project membership check
    ├─ Policy compliance filter
    └─ Return report + audit history
```

## Module Structure

### Core Modules

#### `models.py` (9.2 KB)
Pydantic data models for all domain entities:
- `RunRecord` - Research run orchestration state
- `EvidenceRecord` - Source passages with metadata
- `ClaimRecord` - Material assertions in reports
- `ReviewFinding` - Fact-checking and review results
- `ApprovalRecord` - Human approval tracking
- `ReleaseRecord` - Published internal reports
- `DraftReport` - Work-in-progress report

#### `database.py` (8.8 KB)
Cosmos DB document models for persistence:
- `ProjectGuardRecord` - Tenant/project scope enforcement with epoch
- `RunControlRecord` - Run orchestration state with ETag
- `AuditRecord` - Operation audit trail
- `OutboxRecord` - Event publishing queue
- `ClaimStateRecord` - Claim tracking
- `EvidenceIndexMetadata` - Search index metadata

#### `config.py` (6.4 KB)
Pydantic Settings for configuration:
- `AzureConfig` - Azure service credentials and endpoints
- `ModelConfig` - LLM and embedding model settings
- `ResearchConfig` - Research execution parameters
- `APIConfig` - REST API server configuration
- Cached configuration accessors with `@lru_cache()`

#### `agents.py` (11.5 KB)
Multi-agent orchestration framework:
- `Agent` - Abstract base class for all agents
- `PlannerAgent` - Decomposes research questions
- `SourceSearcherAgent` - Discovers academic sources
- `IngestionAgent` - Extracts passages from documents
- `ResearchAgent` - Retrieves evidence via hybrid search
- `SynthesisAgent` - Generates report from evidence
- `FactCheckerAgent` - Verifies claims independently
- `CriticalReviewerAgent` - Reviews methodology
- `AgentMessage` - Serializable message protocol
- `AgentOrchestrator` - State machine for execution flow

#### `services.py` (11.5 KB)
Business logic and authorization layer:
- `TenantService` - Tenant lifecycle management
- `ProjectService` - Project and membership management
- `ResearchRunService` - Run lifecycle and state transitions
- `ApprovalService` - Approval workflow
- `ReleaseService` - Publication and withdrawal (ADR-015)
- `EvidenceService` - Search, retrieval, and indexing

#### `main.py` (15.5 KB)
FastAPI application with REST endpoints:
- Health and system endpoints
- Project management APIs
- Research run lifecycle APIs
- Approval and release workflow APIs
- Evidence search and retrieval APIs
- CORS middleware
- Error handling
- Lifespan management for service initialization

### Configuration Files

- `.env.example` (1.7 KB) - Template for all environment variables
- `requirements.txt` - Python dependencies
- `Dockerfile` - Containerized deployment

### Documentation

- `README.md` (10.0 KB) - Overview, setup, and quick start
- `IMPLEMENTATION_GUIDE.md` (27.6 KB) - Detailed phase-by-phase implementation
- `ARCHITECTURE.md` (this file) - Architecture and design rationale

### Tests

- `tests/test_models.py` (9.8 KB) - Unit tests for data models and basic services
- Pytest configuration via `requirements.txt`

## Key Design Patterns

### 1. Pydantic Validation

All data crossing API boundaries uses Pydantic models with strict validation:
```python
class ResearchRequest(BaseModel):
    title: str
    primary_question: str
    scope_description: str
    languages: List[str] = Field(default_factory=lambda: ["en"])
    # Automatic validation and JSON serialization
```

### 2. Project Isolation

Every operation includes tenant and project scope enforcement:
```python
async def get_run(
    self,
    tenant_id: str,      # From auth context, never from payload
    project_id: str,     # Validated in ProjectService
    run_id: str
) -> Optional[RunRecord]:
    # Query includes: WHERE tenant_id = ? AND project_id = ?
    # Foreign project runs cannot be accessed
```

### 3. State Machine Orchestration

Deterministic state transitions with agent delegation:
```python
state_machine = {
    "awaiting_scope_confirmation": [PlannerAgent],
    "collecting": [SourceSearcherAgent, IngestionAgent],
    "synthesizing": [ResearchAgent, SynthesisAgent],
    "reviewing": [FactChecker, CriticalReviewer, CitationValidator],
    "awaiting_approval": [OrchestratorAgent]
}
```

### 4. Agent Message Protocol

Versioned, validated messages between agents:
```python
class AgentMessage(BaseModel):
    schema_version: str = "1.0"  # For contract versioning
    run_id: str                  # Immutable run reference
    tenant_id: str               # Project isolation
    project_id: str              # Project isolation
    input_payload: Dict          # Type-specific input
    output_payload: Dict         # Structured output
    status: str                  # pending, processing, completed, failed
```

### 5. Conditional Updates

Optimistic concurrency with ETags for cross-service consistency:
```python
# Cosmos DB supports ETag-based conditional writes
await container.replace_item(
    item_id,
    updated_item,
    match_condition=MatchConditions.IfNotModified,
    etag=current_etag  # Fails if modified by another process
)
```

### 6. Audit Trail

Every significant operation recorded with context:
```python
audit = AuditRecord(
    tenant_id="TEN-001",
    project_id="PRJ-001",
    operation="report_released",
    actor_id="user-123"
)
audit.details = {"release_id": "REL-001", "previous_state": "approved"}
# Persisted to Cosmos DB for history and compliance
```

## Architecture Decision Records (ADRs)

### ADR-001: Deterministic Orchestration
**Decision**: Use explicit state machine, not free-form agent conversation
**Rationale**: Ensures reproducibility, enables replay and recovery, simplifies auditing

### ADR-002: Retrieval Before Generation
**Decision**: LLM knowledge only for planning; all claims from indexed sources
**Rationale**: Prevents hallucinations, enables citation verification, supports contradiction detection

### ADR-012: Project Isolation
**Decision**: Enforce tenant/project scope at every service boundary
**Rationale**: Prevents cross-tenant data leakage, supports multi-tenancy, enables soft multi-tenancy

### ADR-015: Cross-Service Release Protocol
**Decision**: Use Cosmos DB conditional writes + Blob Storage + Service Bus with outbox pattern
**Rationale**: Handles distributed failure modes, preserves invariants across services

### ADR-017: Complete User Journeys
**Decision**: Implement visible outcomes for all paths (success, insufficient evidence, cancellation)
**Rationale**: Users understand system state, no silent failures, meets accessibility requirements

## Security Boundaries

1. **Authentication**: Azure AD identities only
2. **Authorization**: Project-scoped role-based (Researcher, Reviewer, Publisher, Admin)
3. **Data Isolation**: Tenant and project partition keys enforced
4. **Source Handling**: Retrieved documents never treated as system input
5. **Credential Management**: Azure Key Vault for external API secrets
6. **Audit Logging**: All operations recorded with actor and timestamp

## Scalability Considerations

- **Horizontal Scaling**: Stateless API servers behind load balancer
- **Partition Key**: `projectId` for Cosmos DB to enable scaling within organization
- **Caching**: Project-scoped cache keys with policy epoch invalidation
- **Search Index**: Per-run or per-project indices for parallelism
- **Async Processing**: Service Bus for decoupled agent execution

## Error Handling & Recovery

### Run Failures
- **Transient**: Automatic retry with exponential backoff
- **Permanent**: Transition to `failed` state with visible reason
- **User Recoverable**: Allow retry with different parameters (next run)

### Cross-Service Failures
- **Blob Storage Unavailable**: Leave release in `release_pending`, retry
- **Cosmos Transaction Fails**: No release marker created, no loss of state
- **Service Bus Delivery Fails**: Durable outbox retries indefinitely

### Agent Failures
- **Validation Failure**: Agent output rejected, run transitions to `reviewing` or `failed`
- **Timeout**: Configurable per-agent, increments work epoch to cancel in-flight
- **LLM API Error**: Propagates to orchestrator, user can retry

## Monitoring & Observability

- **OpenTelemetry**: Traces for every agent execution
- **Application Insights**: Metrics, logs, exceptions
- **Custom Events**: Research-specific tracking (evidence count, search latency, budget)
- **Audit Trail**: Every operation logged to Cosmos DB

## Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| API Response | <500ms | For simple queries |
| Evidence Search | <1s | Hybrid search, max 20 results |
| Report Synthesis | <30s | LLM call with context |
| Fact-Check Cycle | <5s per claim | Parallel execution |
| Release Commit | <2s | Cosmos transaction |

## Dependencies

### External Services
- **Azure Cosmos DB**: Project and run state persistence
- **Azure Blob Storage**: Evidence document storage
- **Azure AI Search**: Passage retrieval and vector search
- **Azure Service Bus**: Asynchronous task queue
- **Azure OpenAI**: LLM for planning, synthesis, review
- **Academic APIs**: OpenAlex, Crossref, arXiv for discovery

### Python Libraries
- FastAPI: REST API framework
- Pydantic: Data validation
- Azure SDK: Service integration
- OpenAI SDK: LLM integration
- PyMuPDF, Beautiful Soup: Document parsing

## Future Enhancements

1. **Multi-turn Refinement**: Allow researchers to refine questions based on interim results
2. **Evidence Visualization**: Graph view of claim-evidence relationships
3. **Comparative Analysis**: Multi-report comparison for consensus assessment
4. **Dataset Integration**: Ingest and analyze research datasets
5. **Model Fine-tuning**: Train domain-specific models for better citation accuracy
6. **Batch Processing**: Research portfolio for multiple parallel investigations
7. **External Publication**: Controlled export to preprint servers or journals
8. **Webhook Notifications**: Event-driven alerts for stakeholders

---

**Document Version**: 1.0  
**Last Updated**: 2026-09-09  
**Status**: Specification Complete, Implementation In Progress
