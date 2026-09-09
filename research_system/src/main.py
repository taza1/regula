"""FastAPI application for the research system."""

from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel

from src.config import get_api_config, get_azure_config
from src.models import (
    RunState, ResearchRequest, RunRecord, ProjectModel,
    EvidenceRecord, ClaimRecord, ReviewFinding
)
from src.services import (
    TenantService, ProjectService, ResearchRunService,
    ApprovalService, ReleaseService, EvidenceService
)
from src.agents import AgentOrchestrator


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    global tenant_service, project_service, run_service
    global approval_service, release_service, evidence_service, orchestrator
    
    # Startup
    tenant_service = TenantService()
    project_service = ProjectService()
    run_service = ResearchRunService()
    approval_service = ApprovalService()
    release_service = ReleaseService()
    evidence_service = EvidenceService()
    orchestrator = AgentOrchestrator()
    
    print("✓ Research system services initialized")
    
    yield
    
    # Shutdown
    print("✓ Research system shutdown")


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
    languages: List[str] = ["en"]
    approved_source_domains: List[str] = []
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
        "version": api_config.api_version
    }


@app.get("/api/v1/system/info")
async def system_info():
    """Get system information and configuration."""
    return {
        "system": "Multi-Agent Research System",
        "version": api_config.api_version,
        "azure_region": azure_config.blob_storage_account,
        "models": {
            "llm": "gpt-4-turbo",
            "embedding": "text-embedding-3-small"
        }
    }


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
        # TODO: Verify user is researcher in project
        
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
        # TODO: Get authenticated user (approver_id)
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
    try:
        # TODO: Verify approval and run state
        # TODO: Freeze artifacts and compute digest
        # TODO: Execute ADR-015 release protocol
        
        release_id = await release_service.prepare_release(
            tenant_id, project_id, run_id,
            report_revision=1,
            approval_record=None  # TODO: Fetch approval
        )
        
        if not release_id:
            raise HTTPException(status_code=409, detail="Failed to prepare release")
        
        return {
            "release_id": release_id,
            "message": "Report released for internal publication"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    return {
        "error": exc.detail,
        "status_code": exc.status_code
    }


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
