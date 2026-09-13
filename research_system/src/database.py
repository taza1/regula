"""Database models and access patterns for Cosmos DB."""

from typing import Optional, List, Dict, Any
from datetime import datetime
from abc import ABC, abstractmethod
import hashlib
import json


class CosmosModel(ABC):
    """Base model for Cosmos DB documents."""
    
    def __init__(self):
        self.id: str = ""
        self.partition_key: str = ""
        self.type: str = ""
        self.created_at: datetime = datetime.utcnow()
    
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary for Cosmos DB."""
        pass
    
    @abstractmethod
    def get_partition_key(self) -> str:
        """Get partition key for this document."""
        pass


class ProjectGuardRecord(CosmosModel):
    """Project-scoped authorization and policy epoch marker."""
    
    def __init__(self, tenant_id: str, project_id: str):
        super().__init__()
        self.id = f"{project_id}#guard"
        self.partition_key = project_id
        self.type = "project_guard"
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.policy_epoch = 0
        self.membership_version = 0
        self.member_list: Dict[str, List[str]] = {}  # user_id -> [roles]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "tenantId": self.tenant_id,
            "projectId": self.project_id,
            "policyEpoch": self.policy_epoch,
            "membershipVersion": self.membership_version,
            "memberList": self.member_list,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": datetime.utcnow().isoformat(),
            "_partitionKey": self.partition_key
        }
    
    def get_partition_key(self) -> str:
        return self.partition_key


class RunControlRecord(CosmosModel):
    """Orchestration and state control for a research run."""
    
    def __init__(self, tenant_id: str, project_id: str, run_id: str):
        super().__init__()
        self.id = f"{run_id}#control"
        self.partition_key = project_id
        self.type = "run_control"
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.run_id = run_id
        self.state = "awaiting_scope_confirmation"
        self.report_revision = 1
        self.policy_epoch = 0
        self.work_epoch = 0
        self.e_tag = None
        self.approval_reference: Optional[str] = None
        self.release_marker: Optional[str] = None
        self.release_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "tenantId": self.tenant_id,
            "projectId": self.project_id,
            "runId": self.run_id,
            "state": self.state,
            "reportRevision": self.report_revision,
            "policyEpoch": self.policy_epoch,
            "workEpoch": self.work_epoch,
            "eTag": self.e_tag,
            "approvalReference": self.approval_reference,
            "releaseMarker": self.release_marker,
            "releaseId": self.release_id,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": datetime.utcnow().isoformat(),
            "_partitionKey": self.partition_key
        }
    
    def get_partition_key(self) -> str:
        return self.partition_key


class AuditRecord(CosmosModel):
    """Audit trail for important operations."""
    
    def __init__(self, tenant_id: str, project_id: str, operation: str, actor_id: str):
        super().__init__()
        self.id = f"{datetime.utcnow().isoformat()}#{operation}#{actor_id}"
        self.partition_key = project_id
        self.type = "audit"
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.operation = operation
        self.actor_id = actor_id
        self.details: Dict[str, Any] = {}
        self.result = "success"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "tenantId": self.tenant_id,
            "projectId": self.project_id,
            "operation": self.operation,
            "actorId": self.actor_id,
            "details": self.details,
            "result": self.result,
            "createdAt": self.created_at.isoformat(),
            "_partitionKey": self.partition_key
        }
    
    def get_partition_key(self) -> str:
        return self.partition_key


class OutboxRecord(CosmosModel):
    """Outbox for publishing events to Service Bus."""
    
    def __init__(self, tenant_id: str, project_id: str, event_type: str):
        super().__init__()
        self.id = f"{datetime.utcnow().isoformat()}#{event_type}"
        self.partition_key = project_id
        self.type = "outbox"
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.event_type = event_type
        self.payload: Dict[str, Any] = {}
        self.dispatched = False
        self.dispatch_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "tenantId": self.tenant_id,
            "projectId": self.project_id,
            "eventType": self.event_type,
            "payload": self.payload,
            "dispatched": self.dispatched,
            "dispatchTime": self.dispatch_time.isoformat() if self.dispatch_time else None,
            "createdAt": self.created_at.isoformat(),
            "_partitionKey": self.partition_key
        }
    
    def get_partition_key(self) -> str:
        return self.partition_key


class ClaimStateRecord(CosmosModel):
    """State tracking for individual claims."""
    
    def __init__(self, tenant_id: str, project_id: str, run_id: str, claim_id: str):
        super().__init__()
        self.id = f"{run_id}#{claim_id}"
        self.partition_key = project_id
        self.type = "claim_state"
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.run_id = run_id
        self.claim_id = claim_id
        self.report_revision = 1
        self.claim_text = ""
        self.is_material = False
        self.evidence_ids: List[str] = []
        self.sufficiency_status = "pending_assessment"
        self.review_findings: List[str] = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "tenantId": self.tenant_id,
            "projectId": self.project_id,
            "runId": self.run_id,
            "claimId": self.claim_id,
            "reportRevision": self.report_revision,
            "claimText": self.claim_text,
            "isMaterial": self.is_material,
            "evidenceIds": self.evidence_ids,
            "sufficiencyStatus": self.sufficiency_status,
            "reviewFindings": self.review_findings,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": datetime.utcnow().isoformat(),
            "_partitionKey": self.partition_key
        }
    
    def get_partition_key(self) -> str:
        return self.partition_key


class EvidenceIndexMetadata(CosmosModel):
    """Metadata for evidence indexing in Azure AI Search."""
    
    def __init__(self, tenant_id: str, project_id: str, run_id: str):
        super().__init__()
        self.id = f"{run_id}#index_metadata"
        self.partition_key = project_id
        self.type = "evidence_index_metadata"
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.run_id = run_id
        self.index_name = ""
        self.embedding_model = "text-embedding-3-small"
        self.embedding_dimensions = 1536
        self.generation_time: Optional[datetime] = None
        self.document_count = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "tenantId": self.tenant_id,
            "projectId": self.project_id,
            "runId": self.run_id,
            "indexName": self.index_name,
            "embeddingModel": self.embedding_model,
            "embeddingDimensions": self.embedding_dimensions,
            "generationTime": self.generation_time.isoformat() if self.generation_time else None,
            "documentCount": self.document_count,
            "createdAt": self.created_at.isoformat(),
            "_partitionKey": self.partition_key
        }
    
    def get_partition_key(self) -> str:
        return self.partition_key
