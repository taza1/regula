"""FastAPI application for the research system."""

from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field

from src.config import get_api_config, get_azure_config, get_model_config
from src.models import (
    RunState, ResearchRequest, RunRecord, ProjectModel,
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
    evidence_service = EvidenceService()
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
    tenant_id: str,
    request: CreateProjectRequest
):
    """Create a new research project."""
    try:
        # TODO: Get authenticated user and verify tenant access
        user_id = "user-123"  # Placeholder
        
        project = await project_service.create_project(
            tenant_id=tenant_id,
            name=request.name,
            description=request.description or "",
            max_budget_usd=request.max_budget_usd
        )
        
        # Add creator as admin
        await project_service.add_member(
            tenant_id, project.project_id, user_id, ["admin"]
        )
        
        return {
            "project": project.model_dump(mode='json'),
            "message": "Project created successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/projects/{project_id}")
async def get_project(tenant_id: str, project_id: str):
    """Get project details."""
    try:
        project = await project_service.get_project(tenant_id, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
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
    tenant_id: str,
    project_id: str,
    request: CreateRunRequest
):
    """Create a new research run."""
    try:
        project = await project_service.get_project(tenant_id, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        research_request = ResearchRequest(
            title=request.title,
            primary_question=request.primary_question,
            scope_description=request.scope_description,
            languages=request.languages,
            approved_source_domains=request.approved_source_domains,
            max_sources=request.max_sources,
            max_cost_usd=request.max_cost_usd
        )
        
        run = await run_service.create_run(
            tenant_id, project_id, research_request
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
    tenant_id: str,
    project_id: str,
    run_id: str
):
    """Get research run details."""
    try:
        run = await run_service.get_run(tenant_id, project_id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run.model_dump(mode='json')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/plan")
async def plan_research_run(tenant_id: str, project_id: str, run_id: str):
    """Run the planner agent and persist its bounded plan before confirmation."""
    run = await run_service.get_run(tenant_id, project_id, run_id)
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
        tenant_id=tenant_id,
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
        tenant_id, project_id, run_id, result.output_payload
    )
    return {
        "run_id": run_id,
        "provider": model_client.status(),
        "plan": result.output_payload,
        "message": "Plan created. Review it before confirming scope.",
    }


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/confirm-scope")
async def confirm_research_scope(
    tenant_id: str,
    project_id: str,
    run_id: str,
    request: ConfirmScopeRequest
):
    """Confirm research scope before execution."""
    try:
        if not request.confirmed:
            await run_service.cancel_run(
                tenant_id, project_id, run_id,
                reason=request.reason or "Scope not confirmed"
            )
            return {
                "message": "Research run cancelled",
                "run_id": run_id
            }

        run = await run_service.get_run(tenant_id, project_id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if not run.research_plan:
            raise HTTPException(
                status_code=409,
                detail="Create and review a research plan before confirming scope",
            )
        
        # Transition to queued state
        success = await run_service.update_run_state(
            tenant_id, project_id, run_id,
            RunState.QUEUED
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


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/cancel")
async def cancel_research_run(
    tenant_id: str,
    project_id: str,
    run_id: str
):
    """Cancel a research run."""
    try:
        success = await run_service.cancel_run(
            tenant_id, project_id, run_id,
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
    tenant_id: str,
    project_id: str,
    run_id: str,
    request: RequestApprovalRequest
):
    """Request approval for a report."""
    try:
        run = await run_service.get_run(tenant_id, project_id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.state != RunState.AWAITING_APPROVAL:
            raise HTTPException(
                status_code=409,
                detail="Run is not awaiting approval; release remains blocked",
            )

        # TODO: Replace with authenticated Publisher identity.
        approver_id = "publisher-123"  # Placeholder
        
        approval = await approval_service.request_approval(
            tenant_id, project_id, run_id,
            report_revision=1,
            approver_id=approver_id
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
    tenant_id: str,
    project_id: str,
    run_id: str,
    request: ReleaseReportRequest
):
    """Release an approved report for internal publication."""
    raise HTTPException(
        status_code=501,
        detail=(
            "Internal release is not implemented. Artifact verification, "
            "authenticated approval, and conditional commit are required."
        ),
    )


@app.post("/api/v1/releases/{release_id}/withdraw")
async def withdraw_release(
    tenant_id: str,
    project_id: str,
    release_id: str,
    request: WithdrawReleaseRequest
):
    """Withdraw a published release."""
    try:
        # TODO: Get authenticated publisher
        withdrawn_by = "publisher-123"  # Placeholder
        
        success = await release_service.withdraw_release(
            tenant_id, project_id, release_id,
            reason=request.reason,
            withdrawn_by=withdrawn_by
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
    tenant_id: str,
    project_id: str,
    run_id: str,
    request: SearchEvidenceRequest
):
    """Search evidence for a research run."""
    try:
        results = await evidence_service.search_evidence(
            tenant_id, project_id, run_id,
            query=request.query,
            search_type=request.search_type
        )
        
        return {
            "results": [r.model_dump(mode='json') for r in results],
            "count": len(results)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/projects/{project_id}/evidence/{evidence_id}")
async def get_evidence(
    tenant_id: str,
    project_id: str,
    evidence_id: str
):
    """Get evidence details."""
    try:
        evidence = await evidence_service.get_evidence(
            tenant_id, project_id, evidence_id
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
