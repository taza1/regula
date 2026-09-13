"""Research system package initialization."""

__version__ = "1.0.0"
__author__ = "Research System Team"

from src.models import (
    RunState, SourceType, ReviewFindingSeverity,
    EvidenceRecord, ClaimRecord, ReviewFinding, RunRecord
)
from src.agents import Agent, AgentOrchestrator, AgentRole
from src.services import (
    TenantService, ProjectService, ResearchRunService,
    ApprovalService, ReleaseService, EvidenceService
)
from src.source_connectors import (
    LocalSourceConnector, SourceConnector, SourceRecord
)

__all__ = [
    "RunState",
    "SourceType",
    "ReviewFindingSeverity",
    "EvidenceRecord",
    "ClaimRecord",
    "ReviewFinding",
    "RunRecord",
    "Agent",
    "AgentOrchestrator",
    "AgentRole",
    "TenantService",
    "ProjectService",
    "ResearchRunService",
    "ApprovalService",
    "ReleaseService",
    "EvidenceService",
    "SourceRecord",
    "SourceConnector",
    "LocalSourceConnector",
]
