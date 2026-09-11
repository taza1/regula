"""FastAPI application for the research system."""

from typing import Optional, List
from datetime import datetime
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field

from src.config import get_api_config, get_azure_config, get_model_config
from src.models import (
    ProjectMembership, RunState, ResearchRequest, RunRecord, ProjectModel,
    EvidenceRecord, ClaimRecord, ReviewFinding
)
from src.services import (
    TenantService, ProjectService, ResearchRunService,
    ApprovalService, ReleaseService, EvidenceService
)
from src.agents import AgentMessage, AgentOrchestrator, AgentRole
from src.local_store import LocalStateStore
from src.model_client import ModelConnectionError, ResearchModelClient, create_model_client


# ============================================================================
# Application Lifecycle and Initialization
# ============================================================================

# Global services
tenant_service: Optional[TenantService] = None
project_service: Optional[ProjectService] = None
run_service: Optional[ResearchRunService] = None
approval_service: Optional[ApprovalService] = None
release_service: Optional[ReleaseService] = None
evidence_service: Optional[EvidenceService] = None
orchestrator: Optional[AgentOrchestrator] = None
model_client: Optional[ResearchModelClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    global tenant_service, project_service, run_service
    global approval_service, release_service, evidence_service, orchestrator
    global model_client
    
    # Startup
    store = LocalStateStore(api_config.local_db_path)
    tenant_service = TenantService(store)
    project_service = ProjectService(store)
    run_service = ResearchRunService(store)
    approval_service = ApprovalService(store)
    release_service = ReleaseService(store)
    evidence_service = EvidenceService(store)
    model_client = create_model_client(get_model_config())
    orchestrator = AgentOrchestrator(model_client)
    
    print("Research system services initialized")
    
    yield
    
    # Shutdown
    print("Research system shutdown")


# ============================================================================
# Application Setup
# ============================================================================

api_config = get_api_config()
azure_config = get_azure_config()

app = FastAPI(
    title="Multi-Agent Research System API",
    version=api_config.api_version,
    docs_url="/docs" if api_config.enable_docs else None,
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=api_config.cors_origins,
    allow_credentials=api_config.cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Request/Response Models
# ============================================================================

class CreateProjectRequest(BaseModel):
    """Request to create a project."""
    name: str
    description: Optional[str] = None
    max_budget_usd: float = 100.0


class CreateRunRequest(BaseModel):
    """Request to start a research run."""
    title: str
    primary_question: str
    scope_description: str
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    languages: List[str] = Field(default_factory=lambda: ["en"])
    approved_source_domains: List[str] = Field(default_factory=list)
    max_sources: int = 100
    max_cost_usd: float = 50.0


class ConfirmScopeRequest(BaseModel):
    """Confirm research scope before execution."""
    confirmed: bool
    reason: Optional[str] = None


class RequestApprovalRequest(BaseModel):
    """Request approval for a report."""
    approval_rationale: Optional[str] = None


class ReleaseReportRequest(BaseModel):
    """Request to release a report."""
    approval_id: str


class WithdrawReleaseRequest(BaseModel):
    """Request to withdraw a release."""
    reason: str


class SearchEvidenceRequest(BaseModel):
    """Search evidence request."""
    query: str
    search_type: str = "hybrid"
    limit: int = 20


class IndexEvidenceRequest(BaseModel):
    """Locally index one evidence passage for a research run."""
    evidence: EvidenceRecord


class AuthContext(BaseModel):
    """Local development auth context, replaceable by Entra validation later."""

    tenant_id: str
    user_id: str


async def get_auth_context(
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_user_id: str = Header("local-user", alias="X-User-Id"),
) -> AuthContext:
    """Read the local caller identity from headers instead of query strings."""

    tenant = x_tenant_id.strip()
    user = x_user_id.strip()
    if not tenant or not user:
        raise HTTPException(status_code=401, detail="Missing local auth headers")
    return AuthContext(tenant_id=tenant, user_id=user)


def _validate_tenant_query(tenant_id: Optional[str], auth: AuthContext) -> str:
    """Reject mismatches while old clients migrate away from tenant_id query."""

    if tenant_id is not None and tenant_id != auth.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant header/query mismatch")
    return auth.tenant_id


async def _require_project_role(
    tenant_id: str,
    project_id: str,
    user_id: str,
    roles: list[ProjectMembership],
) -> None:
    allowed = await project_service.verify_user_any_role(
        tenant_id,
        project_id,
        user_id,
        [role.value for role in roles],
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Project role required")


def _parse_optional_datetime(value: Optional[str], field_name: str) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be an ISO-8601 datetime or date",
        ) from error


# ============================================================================
# Health and System Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": api_config.api_version,
        "storage": "sqlite-local",
        "model_provider": get_model_config().model_provider,
    }


@app.get("/api/v1/system/info")
async def system_info():
    """Get system information and configuration."""
    return {
        "system": "Multi-Agent Research System",
        "version": api_config.api_version,
        "azure_region": azure_config.azure_region,
        "models": {
            "llm": get_model_config().openai_model,
            "embedding": get_model_config().embedding_model,
        },
        "model_provider": model_client.status() if model_client else None,
    }


@app.get("/api/v1/ai/status")
async def model_status():
    """Show the selected provider without sending a model request."""
    if not model_client:
        raise HTTPException(status_code=503, detail="Model client is not initialized")
    return model_client.status()


# ============================================================================
# Project Management Endpoints
# ============================================================================

@app.post("/api/v1/projects")
async def create_project(
    request: CreateProjectRequest,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Create a new research project."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        
        project = await project_service.create_project(
            tenant_id=scoped_tenant_id,
            name=request.name,
            description=request.description or "",
            max_budget_usd=request.max_budget_usd
        )
        
        # Add creator as admin
        await project_service.add_member(
            scoped_tenant_id,
            project.project_id,
            auth.user_id,
            ["admin", "researcher", "reviewer", "publisher"],
        )
        
        return {
            "project": project.model_dump(mode='json'),
            "message": "Project created successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/projects/{project_id}")
async def get_project(
    project_id: str,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Get project details."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        project = await project_service.get_project(scoped_tenant_id, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        await _require_project_role(
            scoped_tenant_id,
            project_id,
            auth.user_id,
            [
                ProjectMembership.RESEARCHER,
                ProjectMembership.REVIEWER,
                ProjectMembership.PUBLISHER,
                ProjectMembership.ADMIN,
            ],
        )
        return project.model_dump(mode='json')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Research Run Endpoints
# ============================================================================

@app.post("/api/v1/projects/{project_id}/runs")
async def create_research_run(
    project_id: str,
    request: CreateRunRequest,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Create a new research run."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        project = await project_service.get_project(scoped_tenant_id, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        await _require_project_role(
            scoped_tenant_id,
            project_id,
            auth.user_id,
            [ProjectMembership.RESEARCHER, ProjectMembership.ADMIN],
        )
        
        research_request = ResearchRequest(
            title=request.title,
            primary_question=request.primary_question,
            scope_description=request.scope_description,
            date_range_start=_parse_optional_datetime(
                request.date_range_start, "date_range_start"
            ),
            date_range_end=_parse_optional_datetime(
                request.date_range_end, "date_range_end"
            ),
            languages=request.languages,
            approved_source_domains=request.approved_source_domains,
            max_sources=request.max_sources,
            max_cost_usd=request.max_cost_usd
        )
        
        run = await run_service.create_run(
            scoped_tenant_id, project_id, research_request
        )
        
        return {
            "run": run.model_dump(mode='json'),
            "message": "Research run created. Awaiting scope confirmation."
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/projects/{project_id}/runs/{run_id}")
async def get_research_run(
    project_id: str,
    run_id: str,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Get research run details."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        await _require_project_role(
            scoped_tenant_id,
            project_id,
            auth.user_id,
            [
                ProjectMembership.RESEARCHER,
                ProjectMembership.REVIEWER,
                ProjectMembership.PUBLISHER,
                ProjectMembership.ADMIN,
            ],
        )
        run = await run_service.get_run(scoped_tenant_id, project_id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run.model_dump(mode='json')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/plan")
async def plan_research_run(
    project_id: str,
    run_id: str,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Run the planner agent and persist its bounded plan before confirmation."""
    scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
    await _require_project_role(
        scoped_tenant_id,
        project_id,
        auth.user_id,
        [ProjectMembership.RESEARCHER, ProjectMembership.ADMIN],
    )
    run = await run_service.get_run(scoped_tenant_id, project_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.state != RunState.AWAITING_SCOPE_CONFIRMATION:
        raise HTTPException(
            status_code=409,
            detail="Planning is only allowed while scope confirmation is pending",
        )
    message = AgentMessage(
        agent_role=AgentRole.PLANNER,
        run_id=run_id,
        tenant_id=scoped_tenant_id,
        project_id=project_id,
        input_payload={
            "research_request": run.research_request.model_dump(mode="json")
        },
    )
    try:
        result = await orchestrator.execute_phase(
            RunState.AWAITING_SCOPE_CONFIRMATION.value, message
        )
    except ModelConnectionError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if result.status != "completed":
        raise HTTPException(
            status_code=422,
            detail=result.error_message or "Planner returned an invalid result",
        )
    await run_service.save_research_plan(
        scoped_tenant_id, project_id, run_id, result.output_payload
    )
    return {
        "run_id": run_id,
        "provider": model_client.status(),
        "plan": result.output_payload,
        "message": "Plan created. Review it before confirming scope.",
    }


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/confirm-scope")
async def confirm_research_scope(
    project_id: str,
    run_id: str,
    request: ConfirmScopeRequest,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Confirm research scope before execution."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        await _require_project_role(
            scoped_tenant_id,
            project_id,
            auth.user_id,
            [ProjectMembership.RESEARCHER, ProjectMembership.ADMIN],
        )
        if not request.confirmed:
            success = await run_service.cancel_run(
                scoped_tenant_id, project_id, run_id,
                reason=request.reason or "Scope not confirmed"
            )
            if not success:
                raise HTTPException(status_code=409, detail="Failed to cancel run")
            return {
                "message": "Research run cancelled",
                "run_id": run_id
            }

        run = await run_service.get_run(scoped_tenant_id, project_id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.state != RunState.AWAITING_SCOPE_CONFIRMATION:
            raise HTTPException(
                status_code=409,
                detail="Scope can only be confirmed while awaiting confirmation",
            )
        if not run.research_plan:
            raise HTTPException(
                status_code=409,
                detail="Create and review a research plan before confirming scope",
            )
        
        # Transition to queued state
        success = await run_service.update_run_state(
            scoped_tenant_id, project_id, run_id,
            RunState.QUEUED,
            expected_state=RunState.AWAITING_SCOPE_CONFIRMATION,
        )
        
        if not success:
            raise HTTPException(status_code=409, detail="Failed to confirm scope")
        
        return {
            "message": "Scope confirmed. Research execution starting.",
            "run_id": run_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/execute-local")
async def execute_local_research(
    project_id: str,
    run_id: str,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Run the deterministic offline discovery and ingestion pipeline."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        await _require_project_role(
            scoped_tenant_id,
            project_id,
            auth.user_id,
            [ProjectMembership.RESEARCHER, ProjectMembership.ADMIN],
        )
        run = await run_service.get_run(scoped_tenant_id, project_id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.state != RunState.QUEUED:
            raise HTTPException(
                status_code=409,
                detail="Local execution requires a scope-confirmed queued run",
            )
        if not run.research_plan:
            raise HTTPException(
                status_code=409,
                detail="Create and confirm a research plan before local execution",
            )

        if not await run_service.update_run_state(
            scoped_tenant_id,
            project_id,
            run_id,
            RunState.COLLECTING,
            expected_state=RunState.QUEUED,
        ):
            raise HTTPException(status_code=409, detail="Failed to start local execution")

        result = await evidence_service.discover_and_ingest_plan(
            scoped_tenant_id, project_id, run_id, run.research_plan
        )
        return {
            "run_id": run_id,
            "state": RunState.COLLECTING.value,
            "source_count": len(result["sources"]),
            "evidence_count": len(result["evidence"]),
            "sources": [source.model_dump(mode="json") for source in result["sources"]],
            "evidence": [item.model_dump(mode="json") for item in result["evidence"]],
            "message": "Local discovery and evidence ingestion completed.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/cancel")
async def cancel_research_run(
    project_id: str,
    run_id: str,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Cancel a research run."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        await _require_project_role(
            scoped_tenant_id,
            project_id,
            auth.user_id,
            [ProjectMembership.RESEARCHER, ProjectMembership.ADMIN],
        )
        success = await run_service.cancel_run(
            scoped_tenant_id, project_id, run_id,
            reason="User requested cancellation"
        )
        
        if not success:
            raise HTTPException(status_code=409, detail="Failed to cancel run")
        
        return {
            "message": "Research run cancelled. In-flight calls may still finish.",
            "run_id": run_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Approval and Release Endpoints
# ============================================================================

@app.post("/api/v1/projects/{project_id}/runs/{run_id}/request-approval")
async def request_approval(
    project_id: str,
    run_id: str,
    request: RequestApprovalRequest,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Request approval for a report."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        await _require_project_role(
            scoped_tenant_id,
            project_id,
            auth.user_id,
            [ProjectMembership.PUBLISHER, ProjectMembership.ADMIN],
        )
        run = await run_service.get_run(scoped_tenant_id, project_id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.state != RunState.AWAITING_APPROVAL:
            raise HTTPException(
                status_code=409,
                detail="Run is not awaiting approval; release remains blocked",
            )

        approval = await approval_service.request_approval(
            scoped_tenant_id, project_id, run_id,
            report_revision=1,
            approver_id=auth.user_id
        )
        
        if not approval:
            raise HTTPException(status_code=409, detail="Failed to create approval")
        
        return {
            "approval": approval.model_dump(mode='json'),
            "message": "Approval request created"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/release")
async def release_report(
    project_id: str,
    run_id: str,
    request: ReleaseReportRequest,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Release an approved report for internal publication."""
    scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
    await _require_project_role(
        scoped_tenant_id,
        project_id,
        auth.user_id,
        [ProjectMembership.PUBLISHER, ProjectMembership.ADMIN],
    )
    raise HTTPException(
        status_code=501,
        detail=(
            "Internal release is not implemented. Artifact verification, "
            "authenticated approval, and conditional commit are required."
        ),
    )


@app.post("/api/v1/releases/{release_id}/withdraw")
async def withdraw_release(
    release_id: str,
    request: WithdrawReleaseRequest,
    project_id: str,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Withdraw a published release."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        await _require_project_role(
            scoped_tenant_id,
            project_id,
            auth.user_id,
            [ProjectMembership.PUBLISHER, ProjectMembership.ADMIN],
        )
        
        success = await release_service.withdraw_release(
            scoped_tenant_id, project_id, release_id,
            reason=request.reason,
            withdrawn_by=auth.user_id
        )
        
        if not success:
            raise HTTPException(status_code=409, detail="Failed to withdraw release")
        
        return {
            "message": "Release withdrawn",
            "release_id": release_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Evidence and Search Endpoints
# ============================================================================

@app.post("/api/v1/projects/{project_id}/runs/{run_id}/search")
async def search_evidence(
    project_id: str,
    run_id: str,
    request: SearchEvidenceRequest,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Search evidence for a research run."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        await _require_project_role(
            scoped_tenant_id,
            project_id,
            auth.user_id,
            [
                ProjectMembership.RESEARCHER,
                ProjectMembership.REVIEWER,
                ProjectMembership.PUBLISHER,
                ProjectMembership.ADMIN,
            ],
        )
        results = await evidence_service.search_evidence(
            scoped_tenant_id, project_id, run_id,
            query=request.query,
            search_type=request.search_type,
            limit=request.limit,
        )
        
        return {
            "results": [r.model_dump(mode='json') for r in results],
            "count": len(results)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/evidence")
async def index_evidence(
    project_id: str,
    run_id: str,
    request: IndexEvidenceRequest,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Store one evidence passage in the local searchable evidence index."""
    scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
    await _require_project_role(
        scoped_tenant_id,
        project_id,
        auth.user_id,
        [ProjectMembership.RESEARCHER, ProjectMembership.ADMIN],
    )
    evidence = request.evidence
    if (
        evidence.tenant_id != scoped_tenant_id
        or evidence.project_id != project_id
        or evidence.run_id != run_id
    ):
        raise HTTPException(status_code=400, detail="Evidence scope does not match request path")
    if not await run_service.get_run(scoped_tenant_id, project_id, run_id):
        raise HTTPException(status_code=404, detail="Research run not found")
    if not await evidence_service.index_evidence(
        scoped_tenant_id, project_id, run_id, [evidence]
    ):
        raise HTTPException(status_code=409, detail="Evidence could not be indexed")
    return {"evidence": evidence.model_dump(mode="json"), "message": "Evidence indexed"}


@app.get("/api/v1/projects/{project_id}/evidence/{evidence_id}")
async def get_evidence(
    project_id: str,
    evidence_id: str,
    tenant_id: Optional[str] = Query(None, deprecated=True),
    auth: AuthContext = Depends(get_auth_context),
):
    """Get evidence details."""
    try:
        scoped_tenant_id = _validate_tenant_query(tenant_id, auth)
        await _require_project_role(
            scoped_tenant_id,
            project_id,
            auth.user_id,
            [
                ProjectMembership.RESEARCHER,
                ProjectMembership.REVIEWER,
                ProjectMembership.PUBLISHER,
                ProjectMembership.ADMIN,
            ],
        )
        evidence = await evidence_service.get_evidence(
            scoped_tenant_id, project_id, evidence_id
        )
        
        if not evidence:
            raise HTTPException(status_code=404, detail="Evidence not found")
        
        return evidence.model_dump(mode='json')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code},
    )


# ============================================================================
# Root Endpoint
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Multi-Agent Research System",
        "api_version": api_config.api_version,
        "docs": "/docs" if api_config.enable_docs else None
    }
