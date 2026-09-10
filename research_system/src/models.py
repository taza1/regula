"""Core data models for the multi-agent research system."""

from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


class SchemaVersion(str, Enum):
    """Schema version for data contracts."""
    V1_0 = "1.0"


class SourceType(str, Enum):
    """Type of research source."""
    PAPER = "paper"
    WEBPAGE = "webpage"
    DATASET = "dataset"
    PREPRINT = "preprint"
    REPORT = "report"


class PeerReviewStatus(str, Enum):
    """Peer review status of a source."""
    PEER_REVIEWED = "peer-reviewed"
    PREPRINT = "preprint"
    UNKNOWN = "unknown"


class SourceUseDecision(str, Enum):
    """Authorization status for source usage."""
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    REQUIRES_REVIEW = "requires_review"
    UNKNOWN = "unknown"


class EvidenceRelation(str, Enum):
    """Relationship between claim and evidence."""
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class ClaimMateriality(str, Enum):
    """Whether a claim is material to conclusions."""
    MATERIAL = "material"
    NON_MATERIAL = "non_material"
    PENDING_ASSESSMENT = "pending_assessment"


class SufficiencyStatus(str, Enum):
    """Evidence sufficiency assessment outcome."""
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    PENDING_ASSESSMENT = "pending_assessment"


class EligibilityStatus(str, Enum):
    """Source eligibility status."""
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    PENDING_REVIEW = "pending_review"


class ReviewFindingSeverity(str, Enum):
    """Severity level of a review finding."""
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewFindingStatus(str, Enum):
    """Status of a review finding."""
    OPEN = "open"
    ACCEPTED_LIMITATION = "accepted_limitation"
    FALSE_POSITIVE = "false_positive"
    RESOLVED = "resolved"


class RunState(str, Enum):
    """State of a research run."""
    AWAITING_SCOPE_CONFIRMATION = "awaiting_scope_confirmation"
    QUEUED = "queued"
    COLLECTING = "collecting"
    SYNTHESIZING = "synthesizing"
    REVIEWING = "reviewing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    RELEASE_PENDING = "release_pending"
    RELEASED = "released"
    WITHDRAWN = "withdrawn"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ADJUDICATION_REQUIRED = "adjudication_required"


class TenantModel(BaseModel):
    """Tenant information."""
    model_config = ConfigDict(from_attributes=True)
    
    tenant_id: str
    name: str
    created_at: datetime


class ProjectMembership(str, Enum):
    """Project role assignments."""
    RESEARCHER = "researcher"
    REVIEWER = "reviewer"
    PUBLISHER = "publisher"
    ADMIN = "admin"


class ProjectModel(BaseModel):
    """Research project definition."""
    model_config = ConfigDict(from_attributes=True)
    
    schema_version: SchemaVersion = SchemaVersion.V1_0
    tenant_id: str
    project_id: str
    name: str
    description: Optional[str] = None
    members: Dict[str, List[ProjectMembership]] = Field(default_factory=dict)
    data_policy_version: str
    max_budget_usd: float
    created_at: datetime
    updated_at: datetime


class ResearchRequest(BaseModel):
    """Initial research request from user."""
    model_config = ConfigDict(from_attributes=True)
    
    title: str
    primary_question: str
    scope_description: str
    date_range_start: Optional[datetime] = None
    date_range_end: Optional[datetime] = None
    languages: List[str] = Field(default_factory=lambda: ["en"])
    approved_source_domains: List[str] = Field(default_factory=list)
    excluded_domains: List[str] = Field(default_factory=list)
    max_sources: int = 100
    max_cost_usd: float = 50.0
    max_duration_seconds: int = 3600


class EvidenceLink(BaseModel):
    """Link between claim and supporting evidence."""
    evidence_id: str
    relation: EvidenceRelation


class ClaimRecord(BaseModel):
    """A factual claim in the report."""
    model_config = ConfigDict(from_attributes=True)
    
    schema_version: SchemaVersion = SchemaVersion.V1_0
    tenant_id: str
    project_id: str
    run_id: str
    report_revision: int
    claim_id: str
    text: str
    material: bool
    evidence_links: List[EvidenceLink] = Field(default_factory=list)
    assertion_scope: str  # "single-origin", "multiple-origin", etc.
    sufficiency_assessment_id: Optional[str] = None
    confidence: float = 0.0
    limitations: List[str] = Field(default_factory=list)
    status: str = "pending_review"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceRecord(BaseModel):
    """A passage of evidence supporting claims."""
    model_config = ConfigDict(from_attributes=True)
    
    schema_version: SchemaVersion = SchemaVersion.V1_0
    tenant_id: str
    project_id: str
    run_id: str
    report_revision: int
    evidence_id: str
    source_id: str
    source_type: SourceType
    title: str
    url: str
    doi: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    retrieved_at: datetime
    peer_review_status: PeerReviewStatus
    section: Optional[str] = None
    page: Optional[int] = None
    passage: str
    content_hash: str
    license: Optional[str] = None
    source_use_decision: SourceUseDecision
    independence_group_ids: List[str] = Field(default_factory=list)
    independence_status: str = "assessed"
    quality_assessment_id: Optional[str] = None
    eligibility_status: EligibilityStatus
    policy_version: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReviewFinding(BaseModel):
    """Result of fact-checking or critical review."""
    model_config = ConfigDict(from_attributes=True)
    
    schema_version: SchemaVersion = SchemaVersion.V1_0
    tenant_id: str
    project_id: str
    run_id: str
    report_revision: int
    finding_id: str
    claim_id: str
    severity: ReviewFindingSeverity
    category: str  # "citation-entailment", "methodology", etc.
    control_class: str  # "evidence", "security", "privacy", etc.
    status: ReviewFindingStatus
    verdict: str  # "supported", "contradicted", "insufficient_evidence", etc.
    explanation: str
    required_action: Optional[str] = None
    reviewer_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RunRecord(BaseModel):
    """Orchestration state for a research run."""
    model_config = ConfigDict(from_attributes=True)
    
    schema_version: SchemaVersion = SchemaVersion.V1_0
    tenant_id: str
    project_id: str
    run_id: str
    research_request: ResearchRequest
    state: RunState
    report_revision: int = 1
    configuration_snapshot_id: str
    policy_epoch: int
    claims: List[str] = Field(default_factory=list)
    findings: List[str] = Field(default_factory=list)
    research_plan: Optional[Dict[str, Any]] = None
    spent_budget_usd: float = 0.0
    start_time: datetime
    updated_time: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ApprovalRecord(BaseModel):
    """Human approval for report release."""
    model_config = ConfigDict(from_attributes=True)
    
    schema_version: SchemaVersion = SchemaVersion.V1_0
    tenant_id: str
    project_id: str
    run_id: str
    report_revision: int
    approval_id: str
    approved_bundle_digest: str
    approver_id: str
    approved_at: datetime
    approval_rationale: Optional[str] = None
    validity: bool = True


class ReleaseRecord(BaseModel):
    """Published internal release of a report."""
    model_config = ConfigDict(from_attributes=True)
    
    schema_version: SchemaVersion = SchemaVersion.V1_0
    tenant_id: str
    project_id: str
    run_id: str
    report_revision: int
    release_id: str
    released_at: datetime
    released_by: str
    approval_reference: str
    report_blob_url: str
    manifest_blob_url: str
    is_withdrawn: bool = False
    withdrawal_reason: Optional[str] = None
    withdrawn_at: Optional[datetime] = None
    withdrawn_by: Optional[str] = None


class DraftReport(BaseModel):
    """Work-in-progress research report."""
    model_config = ConfigDict(from_attributes=True)
    
    schema_version: SchemaVersion = SchemaVersion.V1_0
    tenant_id: str
    project_id: str
    run_id: str
    report_revision: int
    title: str
    abstract: str
    conclusions: str
    limitations: List[str] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    references: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
