"""API service implementations for research system."""

from typing import Optional, List, Dict, Any, TypedDict
from datetime import datetime
import hashlib
import re
import uuid
from abc import ABC, abstractmethod

from src.models import (
    RunState, ResearchRequest, RunRecord, ProjectModel, 
    ApprovalRecord, ReleaseRecord, TenantModel, EvidenceRecord, ClaimRecord,
    ProjectMembership,
)
from src.config import get_research_config, get_azure_config
from src.local_store import LocalStateStore
from src.source_connectors import (
    FallbackSourceConnector,
    LocalSourceConnector,
    OpenAlexConnector,
    SourceConnector,
    SourceRecord,
)


class DiscoveryIngestionResult(TypedDict):
    """Typed result of the local planner-query pipeline."""

    sources: List[SourceRecord]
    evidence: List[EvidenceRecord]


def _default_store() -> LocalStateStore:
    from src.config import get_api_config

    return LocalStateStore(get_api_config().local_db_path)


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
        # TODO: Persist claim to Cosmos DB
        # TODO: Update run's claim list
        return True
    
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
        approver_id: str
    ) -> Optional[ApprovalRecord]:
        """Request approval for a report."""
        # TODO: Validate run and report
        # TODO: Verify approver is not the requester (if policy requires)
        # TODO: Compute approved bundle digest
        
        approval = ApprovalRecord(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            report_revision=report_revision,
            approval_id=f"APR-{uuid.uuid4().hex[:8].upper()}",
            approved_bundle_digest=f"SHA256-{uuid.uuid4().hex[:16].upper()}",
            approver_id=approver_id,
            approved_at=datetime.utcnow()
        )
        
        self.store.put(
            "approval",
            tenant_id,
            project_id,
            approval.approval_id,
            approval.model_dump(mode="json"),
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
        """Prepare artifacts for release."""
        if (
            approval_record is None
            or not approval_record.validity
            or approval_record.tenant_id != tenant_id
            or approval_record.project_id != project_id
            or approval_record.run_id != run_id
            or approval_record.report_revision != report_revision
        ):
            return None
        # TODO: Freeze report, evidence manifest, evaluation results
        # TODO: Verify manifest signatures
        # TODO: Upload to private Blob Storage
        # Returns release ID if successful
        
        release_id = f"REL-{uuid.uuid4().hex[:8].upper()}"
        return release_id
    
    async def commit_release(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        release_id: str,
        approval_record: ApprovalRecord
    ) -> Optional[ReleaseRecord]:
        """Commit release with ADR-015 invariants."""
        if not approval_record.validity:
            return None
        run_service = ResearchRunService(self.store)
        run = await run_service.get_run(tenant_id, project_id, run_id)
        if not run or run.state != RunState.APPROVED:
            return None

        # TODO: Replace this local sequence with the conditional Cosmos transaction:
        #   1. Check authorization and project guard version
        #   2. Check approval still valid
        #   3. Verify run state is approved
        #   4. Update run state to released
        #   5. Create release marker
        #   6. Record audit and outbox events
        # TODO: Dispatch outbox to Service Bus
        # TODO: Handle storage failures and stale approvals
        
        release = ReleaseRecord(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            report_revision=approval_record.report_revision,
            release_id=release_id,
            released_at=datetime.utcnow(),
            released_by=approval_record.approver_id,
            approval_reference=approval_record.approval_id,
            report_blob_url="https://storage.blob.core.windows.net/...",
            manifest_blob_url="https://storage.blob.core.windows.net/..."
        )
        
        self.store.put(
            "release", tenant_id, project_id, release_id, release.model_dump(mode="json")
        )
        await run_service.update_run_state(
            tenant_id,
            project_id,
            run_id,
            RunState.RELEASED,
            revision=approval_record.report_revision,
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
        requested_limit = configured_limit if max_sources is None else max_sources
        if int(requested_limit) <= 0:
            return []
        total_limit = max(
            1, min(int(requested_limit), configured_limit, 1000)
        )
        sources: List[SourceRecord] = []
        seen_ids: set[str] = set()
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
                if source.source_id in seen_ids:
                    continue
                seen_ids.add(source.source_id)
                scoped_source = source.model_copy(
                    update={
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "run_id": run_id,
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
            content_hash = hashlib.sha256(passage.encode("utf-8")).hexdigest()
            evidence_id = "EVD-" + hashlib.sha256(
                f"{tenant_id}|{project_id}|{run_id}|{source.source_id}|{content_hash}".encode(
                    "utf-8"
                )
            ).hexdigest()[:16].upper()
            evidence = EvidenceRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                report_revision=run.report_revision,
                evidence_id=evidence_id,
                source_id=source.source_id,
                source_type=source.source_type,
                title=source.title,
                url=source.url,
                doi=source.doi,
                authors=source.authors,
                published_at=source.published_at,
                retrieved_at=datetime.utcnow(),
                peer_review_status=source.peer_review_status,
                section="abstract",
                passage=passage,
                content_hash=f"sha256:{content_hash}",
                license=source.license,
                source_use_decision=source.source_use_decision,
                independence_group_ids=[source.source_id],
                eligibility_status=source.eligibility_status,
                policy_version=source.policy_version,
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
        """Search evidence with hybrid retrieval."""
        if not query.strip():
            return []
        terms = [
            term
            for term in re.findall(r"[a-z0-9]{2,}", query.casefold())
            if term.strip()
        ]
        candidates = self.store.list("evidence", tenant_id, project_id, limit=1000)
        ranked: list[tuple[int, EvidenceRecord]] = []
        for payload in candidates:
            evidence = EvidenceRecord.model_validate(payload)
            if evidence.run_id != run_id or evidence.source_use_decision.value != "allowed":
                continue
            haystack_text = " ".join(
                [evidence.title, evidence.passage, evidence.url, evidence.doi or ""]
                + evidence.authors
            ).casefold()
            haystack_tokens = re.findall(r"[a-z0-9]{2,}", haystack_text)
            score = sum(haystack_tokens.count(term) for term in terms)
            if score:
                ranked.append((score, evidence))
        ranked.sort(key=lambda item: (-item[0], item[1].created_at))
        return [evidence for _, evidence in ranked[: max(1, min(limit, 100))]]
    
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
            latest_query_days=config.latest_query_days,
        )
    if provider == "openalex_with_local_fallback":
        return FallbackSourceConnector(
            OpenAlexConnector(
                base_url=config.openalex_base_url,
                mailto=config.openalex_mailto,
                timeout_seconds=config.openalex_timeout_seconds,
                latest_query_days=config.latest_query_days,
            )
        )
    raise ValueError(
        "SOURCE_CONNECTOR must be one of: local, openalex, openalex_with_local_fallback"
    )
