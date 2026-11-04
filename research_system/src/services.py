"""API service implementations for research system."""

from typing import Optional, List, Dict, Any, TypedDict
from datetime import datetime
import asyncio
import hashlib
import json
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlparse

from src.models import (
    RunState, ResearchRequest, RunRecord, ProjectModel,
    ApprovalRecord, ReleaseRecord, TenantModel, EvidenceRecord, ClaimRecord,
    ProjectMembership, SourceSnapshotRecord, PassageRecord, DraftReport,
    EvidenceLink, EvidenceRelation,
)
from src.config import get_research_config, get_azure_config
from src.local_store import LocalStateStore
from src.audit import AuditService
from src.bundle import blocking_findings, bundle_digest, load_bundle
from src.source_connectors import (
    FallbackSourceConnector,
    LocalSourceConnector,
    OpenAlexConnector,
    CrossrefConnector,
    ArxivConnector,
    CompositeScholarlyConnector,
    SourceConnector,
    SourceRecord,
)
from src.evidence_extraction import chunk_text, fetch_document
from src.retrieval import (
    build_contradictory_queries,
    build_fts_query,
    cosine,
    embed_text,
    reciprocal_rank_fusion,
)

_KEYWORD_WEIGHT = 0.6
_SEMANTIC_WEIGHT = 0.4
_SEMANTIC_MIN_SIMILARITY = 0.05
_CANDIDATE_LIMIT = 200


class DiscoveryIngestionResult(TypedDict):
    """Typed result of the local planner-query pipeline."""

    sources: List[SourceRecord]
    evidence: List[EvidenceRecord]


class SynthesisResult(TypedDict):
    """Typed result of the local evidence-to-draft skeleton."""

    draft: DraftReport
    claims: List[ClaimRecord]


def _default_store() -> LocalStateStore:
    from src.config import get_api_config

    return LocalStateStore(get_api_config().local_db_path)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_doi(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    doi = value.strip().casefold()
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    return doi or None


def _title_fingerprint(value: str) -> str:
    words = re.findall(r"[a-z0-9]{2,}", value.casefold())
    return "-".join(words[:12])


def _domain_matches(hostname: str, policy_domain: str) -> bool:
    hostname = hostname.casefold().rstrip(".")
    policy_domain = policy_domain.casefold().strip().removeprefix("*.").rstrip(".")
    return bool(policy_domain) and (hostname == policy_domain or hostname.endswith("." + policy_domain))


def source_passes_governance(
    source: SourceRecord,
    *,
    approved_domains: Optional[List[str]] = None,
    excluded_domains: Optional[List[str]] = None,
    allowed_licenses: Optional[List[str]] = None,
    require_permissive_license: bool = False,
) -> bool:
    """Apply domain and text-extraction license policy before persistence."""

    hostname = (urlparse(source.url).hostname or "").casefold()
    approved = [item for item in (approved_domains or []) if item.strip()]
    excluded = [item for item in (excluded_domains or []) if item.strip()]
    if excluded and any(_domain_matches(hostname, item) for item in excluded):
        return False
    if approved and not any(_domain_matches(hostname, item) for item in approved):
        return False
    license_value = (source.license or "").casefold()
    allowed = [item.casefold().strip() for item in (allowed_licenses or []) if item.strip()]
    if require_permissive_license and not license_value:
        return False
    normalized_license = license_value.replace("_", "-")
    license_matches = any(item in normalized_license for item in allowed)
    if "cc-by" in allowed and "creativecommons.org/licenses/by" in normalized_license:
        license_matches = True
    if "cc0" in allowed and "creativecommons.org/publicdomain/zero" in normalized_license:
        license_matches = True
    if license_value and allowed and not license_matches:
        return False
    return True


def canonical_source_id(source: SourceRecord) -> str:
    """Return a provider-independent local canonical ID for deduplication."""

    doi = _normalize_doi(source.doi)
    if not doi:
        for value in (source.metadata or {}).get("doi"), (source.metadata or {}).get("crossref_doi"):
            doi = _normalize_doi(value)
            if doi:
                break
    if doi:
        if "10.48550/arxiv." in doi:
            arxiv_id = re.sub(r"v\d+$", "", doi.split("10.48550/arxiv.", 1)[1].casefold())
            return "CAN-ARXIV-" + _sha256_hex(arxiv_id)[:16].upper()
        return "CAN-DOI-" + _sha256_hex(doi)[:16].upper()
    metadata = source.metadata or {}
    for key in ("openalex_id", "arxiv_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            if key == "arxiv_id":
                value = re.sub(r"v\d+$", "", value.strip().casefold())
            return f"CAN-{key.upper().replace('_', '-')}-" + _sha256_hex(
                value.strip().casefold()
            )[:16].upper()
    arxiv_match = re.search(r"(?:arxiv[.:/])?(\d{4}\.\d{4,5})(?:v\d+)?", f"{source.url} {source.source_id}".casefold())
    if arxiv_match:
        return "CAN-ARXIV-" + _sha256_hex(arxiv_match.group(1))[:16].upper()
    year = str(source.published_at.year) if source.published_at else "unknown"
    fingerprint = _title_fingerprint(source.title)
    return "CAN-TITLE-" + _sha256_hex(f"{fingerprint}|{year}")[:16].upper()


def _first_sentence(text: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return ""
    match = re.search(r"(.{40,240}?[.!?])(?:\s|$)", compact)
    return match.group(1) if match else compact[:240]


class TenantService:
    """Service for tenant management."""

    def __init__(self, store: Optional[LocalStateStore] = None):
        self.store = store or _default_store()
    
    async def create_tenant(self, name: str) -> TenantModel:
        """Create a new tenant."""
        tenant_id = f"TEN-{uuid.uuid4().hex[:8].upper()}"
        tenant = TenantModel(
            tenant_id=tenant_id,
            name=name,
            created_at=datetime.utcnow()
        )
        self.store.put("tenant", tenant_id, "", tenant_id, tenant.model_dump(mode="json"))
        return tenant
    
    async def get_tenant(self, tenant_id: str) -> Optional[TenantModel]:
        """Retrieve tenant by ID."""
        payload = self.store.get("tenant", tenant_id, "", tenant_id)
        return TenantModel.model_validate(payload) if payload else None


class ProjectService:
    """Service for project management and authorization."""

    def __init__(self, store: Optional[LocalStateStore] = None):
        self.store = store or _default_store()
    
    async def create_project(
        self,
        tenant_id: str,
        name: str,
        description: str = "",
        data_policy_version: str = "POL-001",
        max_budget_usd: float = 100.0
    ) -> ProjectModel:
        """Create a new research project."""
        project_id = f"PRJ-{uuid.uuid4().hex[:8].upper()}"
        project = ProjectModel(
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            description=description,
            data_policy_version=data_policy_version,
            max_budget_usd=max_budget_usd,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        self.store.put(
            "project", tenant_id, project_id, project_id, project.model_dump(mode="json")
        )
        return project
    
    async def get_project(self, tenant_id: str, project_id: str) -> Optional[ProjectModel]:
        """Get project with authorization check."""
        payload = self.store.get("project", tenant_id, project_id, project_id)
        return ProjectModel.model_validate(payload) if payload else None
    
    async def add_member(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        roles: List[str]
    ) -> bool:
        """Add member to project with roles."""
        project = await self.get_project(tenant_id, project_id)
        if not project:
            return False
        project.members[user_id] = [ProjectMembership(role) for role in roles]
        project.updated_at = datetime.utcnow()
        self.store.put(
            "project", tenant_id, project_id, project_id, project.model_dump(mode="json")
        )
        return True
    
    async def verify_user_role(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        required_role: str
    ) -> bool:
        """Verify user has required role in project."""
        project = await self.get_project(tenant_id, project_id)
        if not project:
            return False
        return required_role in [
            role.value if hasattr(role, "value") else role
            for role in project.members.get(user_id, [])
        ]

    async def verify_user_any_role(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        required_roles: List[str],
    ) -> bool:
        """Verify user has at least one required role in project."""
        project = await self.get_project(tenant_id, project_id)
        if not project:
            return False
        assigned_roles = {
            role.value if hasattr(role, "value") else role
            for role in project.members.get(user_id, [])
        }
        return bool(assigned_roles & set(required_roles))


class ResearchRunService:
    """Service for managing research runs."""

    _terminal_states = {
        RunState.CANCELLED,
        RunState.RELEASED,
        RunState.WITHDRAWN,
        RunState.INSUFFICIENT_EVIDENCE,
        RunState.BUDGET_EXHAUSTED,
        RunState.FAILED,
    }
    _allowed_transitions = {
        RunState.AWAITING_SCOPE_CONFIRMATION: {
            RunState.QUEUED,
            RunState.CANCELLED,
        },
        RunState.QUEUED: {
            RunState.COLLECTING,
            RunState.CANCELLED,
            RunState.FAILED,
        },
        RunState.COLLECTING: {
            RunState.SYNTHESIZING,
            RunState.INSUFFICIENT_EVIDENCE,
            RunState.CANCELLED,
            RunState.FAILED,
        },
        RunState.SYNTHESIZING: {
            RunState.REVIEWING,
            RunState.CANCELLED,
            RunState.FAILED,
        },
        RunState.REVIEWING: {
            RunState.AWAITING_APPROVAL,
            RunState.ADJUDICATION_REQUIRED,
            RunState.CANCELLED,
            RunState.FAILED,
        },
        RunState.ADJUDICATION_REQUIRED: {
            RunState.SYNTHESIZING,
            RunState.REVIEWING,
            RunState.CANCELLED,
            RunState.FAILED,
        },
        RunState.AWAITING_APPROVAL: {
            RunState.APPROVED,
            RunState.CANCELLED,
            RunState.FAILED,
        },
        RunState.APPROVED: {
            RunState.RELEASE_PENDING,
            RunState.CANCELLED,
            RunState.FAILED,
        },
        RunState.RELEASE_PENDING: {
            RunState.RELEASED,
            RunState.FAILED,
        },
    }
    
    def __init__(self, store: Optional[LocalStateStore] = None):
        self.research_config = get_research_config()
        self.store = store or _default_store()
    
    async def create_run(
        self,
        tenant_id: str,
        project_id: str,
        research_request: ResearchRequest
    ) -> RunRecord:
        """Create a new research run."""
        run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
        config_snapshot_id = f"CFG-{uuid.uuid4().hex[:8].upper()}"
        
        run = RunRecord(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            research_request=research_request,
            state=RunState.AWAITING_SCOPE_CONFIRMATION,
            configuration_snapshot_id=config_snapshot_id,
            policy_epoch=0,
            start_time=datetime.utcnow(),
            updated_time=datetime.utcnow()
        )
        
        self.store.put("run", tenant_id, project_id, run_id, run.model_dump(mode="json"))
        return run
    
    async def get_run(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str
    ) -> Optional[RunRecord]:
        """Get run record with authorization check."""
        payload = self.store.get("run", tenant_id, project_id, run_id)
        return RunRecord.model_validate(payload) if payload else None
    
    async def update_run_state(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        new_state: RunState,
        revision: int = 1,
        expected_state: Optional[RunState] = None,
    ) -> bool:
        """Update run state with local transition checks and optimistic concurrency."""
        run = await self.get_run(tenant_id, project_id, run_id)
        if not run or run.report_revision != revision:
            return False
        if expected_state is not None and run.state != expected_state:
            return False
        if run.state in self._terminal_states:
            return False
        if new_state not in self._allowed_transitions.get(run.state, set()):
            return False
        run.state = new_state
        run.updated_time = datetime.utcnow()
        self.store.put("run", tenant_id, project_id, run_id, run.model_dump(mode="json"))
        return True

    async def save_research_plan(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        plan: Dict[str, Any],
    ) -> bool:
        """Attach a validated planner result to a local run."""
        run = await self.get_run(tenant_id, project_id, run_id)
        if not run:
            return False
        run.research_plan = plan
        run.updated_time = datetime.utcnow()
        self.store.put("run", tenant_id, project_id, run_id, run.model_dump(mode="json"))
        return True
    
    async def record_claim(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        claim: ClaimRecord
    ) -> bool:
        """Record a claim in the run."""
        run = await self.get_run(tenant_id, project_id, run_id)
        if not run or claim.tenant_id != tenant_id or claim.project_id != project_id:
            return False
        self.store.put(
            "claim",
            tenant_id,
            project_id,
            claim.claim_id,
            claim.model_dump(mode="json"),
        )
        if claim.claim_id not in run.claims:
            run.claims.append(claim.claim_id)
            run.updated_time = datetime.utcnow()
            self.store.put(
                "run", tenant_id, project_id, run_id, run.model_dump(mode="json")
            )
        return True

    async def list_claims(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        limit: int = 100,
    ) -> List[ClaimRecord]:
        """List claims belonging to a run."""
        payloads = self.store.list(
            "claim", tenant_id, project_id, limit=max(1, min(limit, 1000))
        )
        return [
            claim
            for payload in payloads
            if (claim := ClaimRecord.model_validate(payload)).run_id == run_id
        ]
    
    async def record_evidence(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        evidence: EvidenceRecord
    ) -> bool:
        """Record evidence in the run."""
        run = await self.get_run(tenant_id, project_id, run_id)
        if not run or evidence.tenant_id != tenant_id or evidence.project_id != project_id:
            return False
        self.store.put(
            "evidence",
            tenant_id,
            project_id,
            evidence.evidence_id,
            evidence.model_dump(mode="json"),
        )
        return True
    
    async def cancel_run(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        reason: str
    ) -> bool:
        """Cancel a research run."""
        return await self.update_run_state(
            tenant_id, project_id, run_id, RunState.CANCELLED
        )


class ApprovalService:
    """Service for managing approvals and releases."""

    def __init__(self, store: Optional[LocalStateStore] = None):
        self.store = store or _default_store()
    
    async def request_approval(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        report_revision: int,
        approver_id: str,
        rationale: Optional[str] = None,
    ) -> Optional[ApprovalRecord]:
        """Approve a reviewed report and bind the approval to its content digest.

        Returns None unless the run is awaiting approval at ``report_revision``,
        a draft exists, and no high/critical finding is still open. The digest
        covers the draft, claims, findings and evidence hashes, so a later change
        to any of them invalidates the approval at release time.
        """
        run_service = ResearchRunService(self.store)
        run = await run_service.get_run(tenant_id, project_id, run_id)
        if (
            not run
            or run.state != RunState.AWAITING_APPROVAL
            or run.report_revision != report_revision
        ):
            return None
        bundle = load_bundle(self.store, tenant_id, project_id, run_id)
        if not bundle or blocking_findings(bundle["findings"]):
            return None

        approval = ApprovalRecord(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            report_revision=report_revision,
            approval_id=f"APR-{uuid.uuid4().hex[:8].upper()}",
            approved_bundle_digest=bundle_digest(bundle),
            approver_id=approver_id,
            approved_at=datetime.utcnow(),
            approval_rationale=rationale,
        )
        if not await run_service.update_run_state(
            tenant_id, project_id, run_id, RunState.APPROVED,
            revision=report_revision, expected_state=RunState.AWAITING_APPROVAL,
        ):
            return None
        self.store.put(
            "approval",
            tenant_id,
            project_id,
            approval.approval_id,
            approval.model_dump(mode="json"),
        )
        AuditService(self.store).record(
            tenant_id, project_id, run_id, approver_id, "approval.granted",
            {"approval_id": approval.approval_id, "digest": approval.approved_bundle_digest},
        )
        return approval
    
    async def get_approval(
        self,
        tenant_id: str,
        project_id: str,
        approval_id: str
    ) -> Optional[ApprovalRecord]:
        """Get approval record."""
        payload = self.store.get("approval", tenant_id, project_id, approval_id)
        return ApprovalRecord.model_validate(payload) if payload else None
    
    async def revoke_approval(
        self,
        tenant_id: str,
        project_id: str,
        approval_id: str,
        reason: str
    ) -> bool:
        """Revoke an approval."""
        approval = await self.get_approval(tenant_id, project_id, approval_id)
        if not approval:
            return False
        approval.validity = False
        self.store.put(
            "approval",
            tenant_id,
            project_id,
            approval_id,
            approval.model_dump(mode="json"),
        )
        return True


class ReleaseService:
    """Service for managing internal report releases."""

    def __init__(self, store: Optional[LocalStateStore] = None):
        self.store = store or _default_store()
    
    async def prepare_release(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        report_revision: int,
        approval_record: ApprovalRecord
    ) -> Optional[str]:
        """Freeze the approved bundle to local release files and mark the run pending.

        Returns None (leaving the run untouched) when the approval is invalid,
        belongs to another run, or the bundle no longer matches the digest that
        was approved. A write failure moves the run to FAILED.
        """
        if (
            approval_record is None
            or not approval_record.validity
            or approval_record.tenant_id != tenant_id
            or approval_record.project_id != project_id
            or approval_record.run_id != run_id
            or approval_record.report_revision != report_revision
        ):
            return None
        run_service = ResearchRunService(self.store)
        run = await run_service.get_run(tenant_id, project_id, run_id)
        if not run or run.state != RunState.APPROVED or run.report_revision != report_revision:
            return None
        bundle = load_bundle(self.store, tenant_id, project_id, run_id)
        if not bundle or bundle_digest(bundle) != approval_record.approved_bundle_digest:
            return None
        if not await run_service.update_run_state(
            tenant_id, project_id, run_id, RunState.RELEASE_PENDING,
            revision=report_revision, expected_state=RunState.APPROVED,
        ):
            return None

        release_id = f"REL-{uuid.uuid4().hex[:8].upper()}"
        report_bytes = json.dumps(bundle, sort_keys=True, indent=2, default=str).encode("utf-8")
        manifest = {
            "release_id": release_id,
            "run_id": run_id,
            "report_revision": report_revision,
            "approval_id": approval_record.approval_id,
            "bundle_digest": approval_record.approved_bundle_digest,
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "evidence_hashes": bundle["evidence_hashes"],
            "frozen_at": datetime.utcnow().isoformat(),
        }
        try:
            directory = self._release_dir(release_id)
            directory.mkdir(parents=True, exist_ok=False)
            (directory / "report.json").write_bytes(report_bytes)
            (directory / "manifest.json").write_text(
                json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8"
            )
        except OSError:
            await run_service.update_run_state(
                tenant_id, project_id, run_id, RunState.FAILED,
                revision=report_revision, expected_state=RunState.RELEASE_PENDING,
            )
            return None
        return release_id

    def _release_dir(self, release_id: str) -> Path:
        return self.store.database_path.parent / "releases" / release_id
    
    async def commit_release(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        release_id: str,
        approval_record: ApprovalRecord
    ) -> Optional[ReleaseRecord]:
        """Verify the frozen artifacts and mark the run released (local files).

        Local stand-in for the conditional Cosmos transaction: it re-checks the
        approval, the run state, and the frozen report against its manifest
        before the single state change. Blob URLs are file:// URIs locally.
        """
        if (
            not approval_record.validity
            or approval_record.tenant_id != tenant_id
            or approval_record.project_id != project_id
            or approval_record.run_id != run_id
        ):
            return None
        run_service = ResearchRunService(self.store)
        run = await run_service.get_run(tenant_id, project_id, run_id)
        if (
            not run
            or run.state != RunState.RELEASE_PENDING
            or run.report_revision != approval_record.report_revision
        ):
            return None

        directory = self._release_dir(release_id)
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            report_bytes = (directory / "report.json").read_bytes()
        except (OSError, ValueError):
            return None
        if (
            manifest.get("report_sha256") != hashlib.sha256(report_bytes).hexdigest()
            or manifest.get("bundle_digest") != approval_record.approved_bundle_digest
            or manifest.get("approval_id") != approval_record.approval_id
        ):
            return None

        release = ReleaseRecord(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            report_revision=approval_record.report_revision,
            release_id=release_id,
            released_at=datetime.utcnow(),
            released_by=approval_record.approver_id,
            approval_reference=approval_record.approval_id,
            report_blob_url=(directory / "report.json").as_uri(),
            manifest_blob_url=(directory / "manifest.json").as_uri(),
        )
        if not await run_service.update_run_state(
            tenant_id, project_id, run_id, RunState.RELEASED,
            revision=approval_record.report_revision, expected_state=RunState.RELEASE_PENDING,
        ):
            return None
        self.store.put(
            "release", tenant_id, project_id, release_id, release.model_dump(mode="json")
        )
        AuditService(self.store).record(
            tenant_id, project_id, run_id, approval_record.approver_id, "release.committed",
            {"release_id": release_id, "approval_id": approval_record.approval_id},
        )
        return release
    
    async def get_release(
        self,
        tenant_id: str,
        project_id: str,
        release_id: str
    ) -> Optional[ReleaseRecord]:
        """Get release record."""
        payload = self.store.get("release", tenant_id, project_id, release_id)
        return ReleaseRecord.model_validate(payload) if payload else None
    
    async def list_releases(
        self,
        tenant_id: str,
        project_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[ReleaseRecord]:
        """List releases in project."""
        return [
            ReleaseRecord.model_validate(payload)
            for payload in self.store.list(
                "release", tenant_id, project_id, limit=limit, offset=offset
            )
        ]
    
    async def withdraw_release(
        self,
        tenant_id: str,
        project_id: str,
        release_id: str,
        reason: str,
        withdrawn_by: str
    ) -> bool:
        """Withdraw a published release."""
        release = await self.get_release(tenant_id, project_id, release_id)
        if not release or release.is_withdrawn:
            return False
        release.is_withdrawn = True
        release.withdrawal_reason = reason
        release.withdrawn_at = datetime.utcnow()
        release.withdrawn_by = withdrawn_by
        self.store.put(
            "release", tenant_id, project_id, release_id, release.model_dump(mode="json")
        )
        AuditService(self.store).record(
            tenant_id, project_id, release.run_id, withdrawn_by, "release.withdrawn",
            {"release_id": release_id, "reason": reason},
        )
        return True


class EvidenceService:
    """Service for managing evidence and search index."""

    def __init__(
        self,
        store: Optional[LocalStateStore] = None,
        connector: Optional[SourceConnector] = None,
    ):
        self.store = store or _default_store()
        self.connector = connector or create_source_connector()

    async def discover_sources(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        search_queries: List[str],
        max_sources: Optional[int] = None,
    ) -> List[SourceRecord]:
        """Discover and persist sources for planner-generated search queries.

        The run lookup is intentionally performed before any connector call so
        a caller cannot create source records outside an existing scoped run.
        """

        run = await ResearchRunService(self.store).get_run(
            tenant_id, project_id, run_id
        )
        if not run:
            return []
        configured_limit = run.research_request.max_sources
        research_config = get_research_config()
        requested_limit = configured_limit if max_sources is None else max_sources
        if int(requested_limit) <= 0:
            return []
        total_limit = max(
            1, min(int(requested_limit), configured_limit, 1000)
        )
        sources: List[SourceRecord] = []
        seen_ids: set[str] = set()
        seen_dois: set[str] = set()
        seen_arxiv_ids: set[str] = set()
        seen_openalex_ids: set[str] = set()
        seen_canonical_ids: set[str] = set()
        for existing in await self.list_sources(tenant_id, project_id, run_id, limit=1000):
            seen_canonical_ids.add(
                existing.metadata.get("canonical_source_id")
                if isinstance(existing.metadata.get("canonical_source_id"), str)
                else canonical_source_id(existing)
            )
        for query in search_queries:
            if not isinstance(query, str) or not query.strip():
                continue
            remaining = total_limit - len(sources)
            if remaining <= 0:
                break
            discovered = await self.connector.search(
                query,
                limit=remaining,
                date_range_start=run.research_request.date_range_start,
                date_range_end=run.research_request.date_range_end,
            )
            for source in discovered:
                if not source_passes_governance(
                    source,
                    approved_domains=run.research_request.approved_source_domains,
                    excluded_domains=run.research_request.excluded_domains,
                    allowed_licenses=research_config.allowed_source_licenses,
                    require_permissive_license=research_config.require_permissive_license,
                ):
                    continue
                canonical_id = canonical_source_id(source)
                doi = _normalize_doi(source.doi or source.metadata.get("doi") or source.metadata.get("crossref_doi"))
                arxiv = source.metadata.get("arxiv_id", "")
                arxiv = re.sub(r"v\d+$", "", str(arxiv).casefold()) if arxiv else ""
                openalex = str(source.metadata.get("openalex_id", "")).rstrip("/").casefold()
                if (source.source_id in seen_ids or canonical_id in seen_canonical_ids or
                        (doi and doi in seen_dois) or (arxiv and arxiv in seen_arxiv_ids) or
                        (openalex and openalex in seen_openalex_ids)):
                    continue
                seen_ids.add(source.source_id)
                seen_canonical_ids.add(canonical_id)
                if doi:
                    seen_dois.add(doi)
                if arxiv:
                    seen_arxiv_ids.add(arxiv)
                if openalex:
                    seen_openalex_ids.add(openalex)
                metadata = dict(source.metadata)
                metadata["canonical_source_id"] = canonical_id
                scoped_source = source.model_copy(
                    update={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "run_id": run_id,
                        "metadata": metadata,
                    }
                )
                sources.append(scoped_source)
                self.store.put(
                    "source",
                    tenant_id,
                    project_id,
                    f"{run_id}:{scoped_source.source_id}",
                    scoped_source.model_dump(mode="json"),
                )
                if len(sources) >= total_limit:
                    break
        return sources

    async def list_sources(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        limit: int = 100,
    ) -> List[SourceRecord]:
        """List only source records belonging to the requested run."""

        payloads = self.store.list(
            "source", tenant_id, project_id, limit=max(1, min(limit, 1000))
        )
        return [
            source
            for payload in payloads
            if (source := SourceRecord.model_validate(payload)).run_id == run_id
        ]

    async def ingest_sources(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        sources: List[SourceRecord],
    ) -> List[EvidenceRecord]:
        """Turn discovered local source passages into scoped evidence records.

        Ingestion is content-addressed: retrying the same source produces the
        same evidence ID and updates the same local record rather than
        duplicating evidence.
        """

        run = await ResearchRunService(self.store).get_run(
            tenant_id, project_id, run_id
        )
        if not run:
            return []
        for source in sources:
            if (
                (source.tenant_id and source.tenant_id != tenant_id)
                or (source.project_id and source.project_id != project_id)
                or (source.run_id and source.run_id != run_id)
                or not source.source_id
                or not source.passage.strip()
            ):
                return []

        ingested: List[EvidenceRecord] = []
        for source in sources:
            passage = source.passage.strip()
            content_hash = _sha256_hex(passage)
            canonical_id = (
                source.metadata.get("canonical_source_id")
                if isinstance(source.metadata.get("canonical_source_id"), str)
                else canonical_source_id(source)
            )
            source_identity = f"{tenant_id}|{project_id}|{run_id}|{canonical_id}|{content_hash}"
            snapshot_id = "SSN-" + _sha256_hex(source_identity)[:16].upper()
            passage_id = "PAS-" + _sha256_hex(
                f"{snapshot_id}|abstract|0|{content_hash}"
            )[:16].upper()
            evidence_id = "EVD-" + hashlib.sha256(
                f"{tenant_id}|{project_id}|{run_id}|{canonical_id}|{passage_id}".encode(
                    "utf-8"
                )
            ).hexdigest()[:16].upper()
            retrieved_at = datetime.utcnow()
            snapshot = SourceSnapshotRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                snapshot_id=snapshot_id,
                source_id=source.source_id,
                canonical_source_id=canonical_id,
                provider=source.connector,
                url=source.url,
                doi=source.doi,
                retrieved_at=retrieved_at,
                content_hash=f"sha256:{content_hash}",
                raw_metadata=source.model_dump(mode="json"),
                text=passage,
                storage_uri=f"sqlite://source_snapshot/{snapshot_id}",
            )
            passage_record = PassageRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                passage_id=passage_id,
                source_id=source.source_id,
                source_snapshot_id=snapshot_id,
                canonical_source_id=canonical_id,
                section="abstract",
                offset_start=0,
                offset_end=len(passage),
                text=passage,
                content_hash=f"sha256:{content_hash}",
            )
            evidence = EvidenceRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                report_revision=run.report_revision,
                evidence_id=evidence_id,
                source_id=source.source_id,
                source_snapshot_id=snapshot_id,
                passage_id=passage_id,
                source_type=source.source_type,
                title=source.title,
                url=source.url,
                doi=source.doi,
                authors=source.authors,
                published_at=source.published_at,
                retrieved_at=retrieved_at,
                peer_review_status=source.peer_review_status,
                section="abstract",
                passage=passage,
                content_hash=f"sha256:{content_hash}",
                license=source.license,
                source_use_decision=source.source_use_decision,
                independence_group_ids=[canonical_id],
                eligibility_status=source.eligibility_status,
                policy_version=source.policy_version,
            )
            self.store.put(
                "source_snapshot",
                tenant_id,
                project_id,
                snapshot.snapshot_id,
                snapshot.model_dump(mode="json"),
            )
            self.store.put(
                "passage",
                tenant_id,
                project_id,
                passage_record.passage_id,
                passage_record.model_dump(mode="json"),
            )
            self.store.put(
                "evidence",
                tenant_id,
                project_id,
                evidence.evidence_id,
                evidence.model_dump(mode="json"),
            )
            ingested.append(evidence)
        return ingested

    async def ingest_full_sources(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        sources: List[SourceRecord],
        *,
        max_chars: int = 2000,
        overlap_chars: int = 200,
        max_bytes: int = 10_000_000,
    ) -> List[EvidenceRecord]:
        """Fetch approved full documents, archive snapshots, and ingest chunks.

        This is intentionally explicit; the default local execution path only
        ingests provider abstracts and performs no document network I/O.
        """

        run = await ResearchRunService(self.store).get_run(tenant_id, project_id, run_id)
        if not run:
            return []
        config = get_research_config()
        expanded: List[SourceRecord] = []
        for source in sources:
            if not source_passes_governance(
                source,
                approved_domains=run.research_request.approved_source_domains,
                excluded_domains=run.research_request.excluded_domains,
                allowed_licenses=config.allowed_source_licenses,
                require_permissive_license=config.require_permissive_license,
            ):
                continue
            document = await asyncio.to_thread(
                fetch_document,
                source,
                approved_domains=run.research_request.approved_source_domains,
                excluded_domains=run.research_request.excluded_domains,
                timeout_seconds=config.openalex_timeout_seconds,
                max_bytes=max_bytes,
            )
            for index, passage in enumerate(
                chunk_text(document.text, max_chars=max_chars, overlap_chars=overlap_chars)
            ):
                expanded.append(source.model_copy(update={
                    "passage": passage,
                    "abstract": passage,
                    "metadata": {
                        **source.metadata,
                        "extraction_media_type": document.media_type,
                        "extraction_content_hash": f"sha256:{document.content_hash}",
                        "extraction_chunk_index": index,
                        "extraction_url": document.url,
                    },
                }))
        return await self.ingest_sources(tenant_id, project_id, run_id, expanded)

    async def discover_and_ingest(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        search_queries: List[str],
        max_sources: Optional[int] = None,
    ) -> DiscoveryIngestionResult:
        """Execute the deterministic planner-query -> source -> evidence slice."""

        sources = await self.discover_sources(
            tenant_id, project_id, run_id, search_queries, max_sources=max_sources
        )
        evidence = await self.ingest_sources(
            tenant_id, project_id, run_id, sources
        )
        return {"sources": sources, "evidence": evidence}

    async def discover_and_ingest_plan(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        plan: Dict[str, Any],
        max_sources: Optional[int] = None,
    ) -> DiscoveryIngestionResult:
        """Run discovery and ingestion from a persisted planner result."""

        queries = plan.get("search_queries", [])
        if not isinstance(queries, list):
            return {"sources": [], "evidence": []}
        return await self.discover_and_ingest(
            tenant_id, project_id, run_id, queries, max_sources=max_sources
        )
    
    async def search_evidence(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        query: str,
        search_type: str = "hybrid",  # hybrid, keyword, semantic
        limit: int = 20,
    ) -> List[EvidenceRecord]:
        """Search a run's allowed evidence.

        ``keyword`` ranks with SQLite FTS5 BM25, ``semantic`` ranks by cosine
        similarity of local hashed embeddings, ``hybrid`` fuses both with
        weighted reciprocal-rank fusion, and ``contradictory`` runs hybrid
        searches over negation-expanded queries and fuses them.
        """
        if not query.strip():
            return []
        limit = max(1, min(limit, 100))
        if search_type == "contradictory":
            return await self.search_contradictory_evidence(
                tenant_id, project_id, run_id, query, limit=limit
            )
        if search_type not in ("hybrid", "keyword", "semantic"):
            raise ValueError(f"Unsupported search_type: {search_type}")

        records = self._allowed_evidence(tenant_id, project_id, run_id)
        rankings: list[tuple[float, list[str]]] = []
        if search_type in ("hybrid", "keyword"):
            rankings.append(
                (
                    _KEYWORD_WEIGHT,
                    self._keyword_ranking(tenant_id, project_id, run_id, query, records),
                )
            )
        if search_type in ("hybrid", "semantic"):
            rankings.append((_SEMANTIC_WEIGHT, self._semantic_ranking(query, records)))
        fused = reciprocal_rank_fusion(rankings)
        return [records[evidence_id] for evidence_id, _ in fused[:limit]]

    async def search_contradictory_evidence(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        query: str,
        limit: int = 20,
    ) -> List[EvidenceRecord]:
        """Find evidence that may oppose a claim by searching with negation terms."""
        limit = max(1, min(limit, 100))
        records = self._allowed_evidence(tenant_id, project_id, run_id)
        rankings = []
        for match_query in build_contradictory_queries(query):
            hits = self.store.search_evidence_fts(
                tenant_id, project_id, run_id, match_query, limit=_CANDIDATE_LIMIT
            )
            rankings.append(
                (1.0, [eid for eid, _ in hits if eid in records])
            )
        fused = reciprocal_rank_fusion(rankings)
        return [records[evidence_id] for evidence_id, _ in fused[:limit]]

    def _allowed_evidence(
        self, tenant_id: str, project_id: str, run_id: str
    ) -> dict[str, EvidenceRecord]:
        records: dict[str, EvidenceRecord] = {}
        for payload in self.store.list("evidence", tenant_id, project_id, limit=1000):
            evidence = EvidenceRecord.model_validate(payload)
            if (
                evidence.run_id == run_id
                and evidence.source_use_decision.value == "allowed"
            ):
                records[evidence.evidence_id] = evidence
        return records

    def _keyword_ranking(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        query: str,
        records: dict[str, EvidenceRecord],
    ) -> list[str]:
        match_query = build_fts_query(query)
        if not match_query:
            return []
        hits = self.store.search_evidence_fts(
            tenant_id, project_id, run_id, match_query, limit=_CANDIDATE_LIMIT
        )
        return [evidence_id for evidence_id, _ in hits if evidence_id in records]

    @staticmethod
    def _semantic_ranking(
        query: str, records: dict[str, EvidenceRecord]
    ) -> list[str]:
        query_vector = embed_text(query)
        scored = []
        for evidence_id, evidence in records.items():
            text = " ".join([evidence.title, evidence.passage] + evidence.authors)
            similarity = cosine(query_vector, embed_text(text))
            if similarity > _SEMANTIC_MIN_SIMILARITY:
                scored.append((similarity, evidence_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [evidence_id for _, evidence_id in scored[:_CANDIDATE_LIMIT]]
    
    async def get_evidence(
        self,
        tenant_id: str,
        project_id: str,
        evidence_id: str
    ) -> Optional[EvidenceRecord]:
        """Get evidence record."""
        payload = self.store.get("evidence", tenant_id, project_id, evidence_id)
        return EvidenceRecord.model_validate(payload) if payload else None
    
    async def index_evidence(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        evidence_list: List[EvidenceRecord]
    ) -> bool:
        """Index evidence for retrieval."""
        for evidence in evidence_list:
            if (
                evidence.tenant_id != tenant_id
                or evidence.project_id != project_id
                or evidence.run_id != run_id
            ):
                return False
            self.store.put(
                "evidence",
                tenant_id,
                project_id,
                evidence.evidence_id,
                evidence.model_dump(mode="json"),
            )
        return True


class SynthesisService:
    """Create a deterministic local draft skeleton from accepted evidence."""

    def __init__(self, store: Optional[LocalStateStore] = None):
        self.store = store or _default_store()

    async def synthesize_local(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        limit: int = 5,
    ) -> Optional[SynthesisResult]:
        """Build a cited draft skeleton and claim ledger without publication."""

        run_service = ResearchRunService(self.store)
        run = await run_service.get_run(tenant_id, project_id, run_id)
        if not run:
            return None
        payloads = self.store.list(
            "evidence", tenant_id, project_id, limit=max(1, min(limit, 25))
        )
        evidence_records = [
            evidence
            for payload in payloads
            if (evidence := EvidenceRecord.model_validate(payload)).run_id == run_id
            and evidence.source_use_decision.value == "allowed"
        ][: max(1, min(limit, 25))]
        if not evidence_records:
            return None

        claims: List[ClaimRecord] = []
        for index, evidence in enumerate(evidence_records, start=1):
            claim_text = _first_sentence(evidence.passage)
            claim = ClaimRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                report_revision=run.report_revision,
                claim_id="CLM-" + _sha256_hex(
                    f"{tenant_id}|{project_id}|{run_id}|{evidence.evidence_id}"
                )[:16].upper(),
                text=claim_text
                or f"Evidence from {evidence.title} is available for review.",
                material=True,
                evidence_links=[
                    EvidenceLink(
                        evidence_id=evidence.evidence_id,
                        relation=EvidenceRelation.SUPPORTS,
                    )
                ],
                assertion_scope="single-origin",
                confidence=0.0,
                limitations=[
                    "Local draft skeleton only; claim has not been independently reviewed."
                ],
                status="pending_review",
            )
            await run_service.record_claim(tenant_id, project_id, run_id, claim)
            claims.append(claim)

        references = [
            {
                "evidence_id": evidence.evidence_id,
                "passage_id": evidence.passage_id,
                "source_snapshot_id": evidence.source_snapshot_id,
                "title": evidence.title,
                "url": evidence.url,
                "doi": evidence.doi,
                "authors": evidence.authors,
                "published_at": evidence.published_at,
            }
            for evidence in evidence_records
        ]
        draft = DraftReport(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            report_revision=run.report_revision,
            title=f"Draft: {run.research_request.title}",
            abstract=(
                f"Local draft skeleton based on {len(evidence_records)} eligible "
                "evidence passage(s). This draft is not reviewed or release-ready."
            ),
            conclusions="\n".join(
                f"- {claim.text} [evidence: {claim.evidence_links[0].evidence_id}]"
                for claim in claims
            ),
            limitations=[
                "Generated deterministically from stored evidence only.",
                "No fact-checker, citation validator, critical reviewer, or safety reviewer has approved this draft.",
                "The report cannot be released until mandatory review and approval gates exist.",
            ],
            contradictory_evidence=[],
            references=references,
        )
        self.store.put(
            "draft", tenant_id, project_id, run_id, draft.model_dump(mode="json")
        )
        return {"draft": draft, "claims": claims}


def create_source_connector() -> SourceConnector:
    """Create the configured source connector for local development."""

    config = get_research_config()
    provider = config.source_connector.strip().lower()
    if provider == "local":
        return LocalSourceConnector()
    if provider == "openalex":
        return OpenAlexConnector(
            base_url=config.openalex_base_url,
            mailto=config.openalex_mailto,
            timeout_seconds=config.openalex_timeout_seconds,
            request_interval_seconds=config.openalex_request_interval_seconds,
            latest_query_days=config.latest_query_days,
        )
    if provider == "openalex_with_local_fallback":
        return FallbackSourceConnector(
            OpenAlexConnector(
                base_url=config.openalex_base_url,
                mailto=config.openalex_mailto,
                timeout_seconds=config.openalex_timeout_seconds,
                request_interval_seconds=config.openalex_request_interval_seconds,
                latest_query_days=config.latest_query_days,
            )
        )
    if provider == "crossref":
        return CrossrefConnector(base_url=config.crossref_base_url, mailto=config.crossref_mailto,
                                 timeout_seconds=config.crossref_timeout_seconds,
                                 latest_query_days=config.latest_query_days,
                                 request_interval_seconds=config.crossref_request_interval_seconds)
    if provider == "arxiv":
        return ArxivConnector(base_url=config.arxiv_base_url, timeout_seconds=config.arxiv_timeout_seconds)
    if provider == "scholarly_with_local_fallback":
        return FallbackSourceConnector(CompositeScholarlyConnector((
            OpenAlexConnector(base_url=config.openalex_base_url, mailto=config.openalex_mailto,
                              timeout_seconds=config.openalex_timeout_seconds,
                              latest_query_days=config.latest_query_days,
                              request_interval_seconds=config.openalex_request_interval_seconds),
            CrossrefConnector(base_url=config.crossref_base_url, mailto=config.crossref_mailto,
                              timeout_seconds=config.crossref_timeout_seconds,
                              latest_query_days=config.latest_query_days,
                              request_interval_seconds=config.crossref_request_interval_seconds),
            ArxivConnector(base_url=config.arxiv_base_url, timeout_seconds=config.arxiv_timeout_seconds,
                           request_interval_seconds=config.arxiv_request_interval_seconds),
        )))
    raise ValueError(
        "SOURCE_CONNECTOR must be one of: local, openalex, crossref, arxiv, scholarly_with_local_fallback, openalex_with_local_fallback"
    )
