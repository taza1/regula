"""Unit tests for research system models and services."""

import pytest
from datetime import datetime
from src.models import (
    RunState, ResearchRequest, RunRecord, EvidenceRecord,
    ClaimRecord, ReviewFinding, ProjectModel, SourceType,
    PeerReviewStatus, SourceUseDecision, EligibilityStatus
)


class TestModels:
    """Test data models."""
    
    def test_research_request_creation(self):
        """Test research request initialization."""
        request = ResearchRequest(
            title="Climate Impact",
            primary_question="What is the impact of climate change?",
            scope_description="Focus on recent peer-reviewed studies",
            languages=["en"],
            max_cost_usd=50.0
        )
        
        assert request.title == "Climate Impact"
        assert request.primary_question == "What is the impact of climate change?"
        assert request.max_cost_usd == 50.0
        assert request.languages == ["en"]
    
    def test_run_record_creation(self):
        """Test run record initialization."""
        request = ResearchRequest(
            title="Test", primary_question="Q?", scope_description="S"
        )
        
        run = RunRecord(
            tenant_id="TEN-001",
            project_id="PRJ-001",
            run_id="RUN-001",
            research_request=request,
            state=RunState.AWAITING_SCOPE_CONFIRMATION,
            configuration_snapshot_id="CFG-001",
            policy_epoch=0,
            start_time=datetime.utcnow(),
            updated_time=datetime.utcnow()
        )
        
        assert run.run_id == "RUN-001"
        assert run.state == RunState.AWAITING_SCOPE_CONFIRMATION
        assert run.report_revision == 1
        assert run.spent_budget_usd == 0.0
    
    def test_evidence_record_creation(self):
        """Test evidence record initialization."""
        evidence = EvidenceRecord(
            tenant_id="TEN-001",
            project_id="PRJ-001",
            run_id="RUN-001",
            report_revision=1,
            evidence_id="EV-001",
            source_id="SRC-001",
            source_type=SourceType.PAPER,
            title="Sample Research Paper",
            url="https://example.com/paper.pdf",
            doi="10.1234/example",
            authors=["Author A", "Author B"],
            retrieved_at=datetime.utcnow(),
            peer_review_status=PeerReviewStatus.PEER_REVIEWED,
            passage="This is a research finding about climate change.",
            content_hash="sha256:abc123",
            source_use_decision=SourceUseDecision.ALLOWED,
            eligibility_status=EligibilityStatus.ELIGIBLE,
            policy_version="POL-001"
        )
        
        assert evidence.evidence_id == "EV-001"
        assert evidence.source_type == SourceType.PAPER
        assert evidence.peer_review_status == PeerReviewStatus.PEER_REVIEWED
        assert len(evidence.passage) > 0
    
    def test_claim_record_creation(self):
        """Test claim record initialization."""
        claim = ClaimRecord(
            tenant_id="TEN-001",
            project_id="PRJ-001",
            run_id="RUN-001",
            report_revision=1,
            claim_id="CLM-001",
            text="Global temperatures have increased by 1.1°C since pre-industrial times.",
            material=True,
            confidence=0.92
        )
        
        assert claim.claim_id == "CLM-001"
        assert claim.material == True
        assert claim.confidence == 0.92
        assert claim.status == "pending_review"
    
    def test_project_model_creation(self):
        """Test project model initialization."""
        project = ProjectModel(
            tenant_id="TEN-001",
            project_id="PRJ-001",
            name="Climate Research Initiative",
            description="Comprehensive climate studies",
            data_policy_version="POL-001",
            max_budget_usd=100.0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        assert project.project_id == "PRJ-001"
        assert project.name == "Climate Research Initiative"
        assert project.max_budget_usd == 100.0
    
    def test_run_state_enum(self):
        """Test run state values."""
        assert RunState.AWAITING_SCOPE_CONFIRMATION.value == "awaiting_scope_confirmation"
        assert RunState.RELEASED.value == "released"
        assert RunState.INSUFFICIENT_EVIDENCE.value == "insufficient_evidence"
        assert RunState.CANCELLED.value == "cancelled"
    
    def test_evidence_record_serialization(self):
        """Test evidence record JSON serialization."""
        evidence = EvidenceRecord(
            tenant_id="TEN-001",
            project_id="PRJ-001",
            run_id="RUN-001",
            report_revision=1,
            evidence_id="EV-001",
            source_id="SRC-001",
            source_type=SourceType.PAPER,
            title="Paper",
            url="https://example.com/paper",
            retrieved_at=datetime.utcnow(),
            peer_review_status=PeerReviewStatus.PEER_REVIEWED,
            passage="Content",
            content_hash="sha256:abc",
            source_use_decision=SourceUseDecision.ALLOWED,
            eligibility_status=EligibilityStatus.ELIGIBLE,
            policy_version="POL-001"
        )
        
        serialized = evidence.model_dump(mode='json')
        
        assert serialized["evidence_id"] == "EV-001"
        assert serialized["source_type"] == "paper"
        assert serialized["peer_review_status"] == "peer-reviewed"


class TestServices:
    """Test service layer."""
    
    @pytest.mark.asyncio
    async def test_project_service_create(self):
        """Test project creation."""
        from src.services import ProjectService
        
        service = ProjectService()
        project = await service.create_project(
            tenant_id="TEN-001",
            name="Test Project",
            description="Test"
        )
        
        assert project.project_id.startswith("PRJ-")
        assert project.name == "Test Project"
    
    @pytest.mark.asyncio
    async def test_run_service_create(self):
        """Test research run creation."""
        from src.services import ResearchRunService
        
        service = ResearchRunService()
        request = ResearchRequest(
            title="Test",
            primary_question="Question?",
            scope_description="Scope",
            max_cost_usd=50.0
        )
        
        run = await service.create_run("TEN-001", "PRJ-001", request)
        
        assert run.run_id.startswith("RUN-")
        assert run.state == RunState.AWAITING_SCOPE_CONFIRMATION
        assert run.spent_budget_usd == 0.0
        assert run.configuration_snapshot_id.startswith("CFG-")


class TestAgents:
    """Test agent framework."""
    
    def test_agent_message_creation(self):
        """Test agent message creation."""
        from src.agents import AgentMessage, AgentRole
        
        message = AgentMessage(
            agent_role=AgentRole.PLANNER,
            run_id="RUN-001",
            tenant_id="TEN-001",
            project_id="PRJ-001"
        )
        
        assert message.agent_role == AgentRole.PLANNER
        assert message.status == "pending"
        assert message.schema_version == "1.0"
    
    def test_agent_message_serialization(self):
        """Test agent message serialization."""
        from src.agents import AgentMessage, AgentRole
        import json
        
        message = AgentMessage(
            agent_role=AgentRole.SYNTHESIS,
            run_id="RUN-001",
            tenant_id="TEN-001",
            project_id="PRJ-001",
            input_payload={"test": "data"}
        )
        
        json_str = message.to_queue_message()
        assert isinstance(json_str, str)
        
        deserialized = json.loads(json_str)
        assert deserialized["agent_role"] == "synthesis"
        assert deserialized["input_payload"]["test"] == "data"
    
    def test_agent_orchestrator_initialization(self):
        """Test orchestrator initialization."""
        from src.agents import AgentOrchestrator
        
        orchestrator = AgentOrchestrator()
        
        assert orchestrator is not None
        assert "awaiting_scope_confirmation" in orchestrator.state_machine
        assert "reviewing" in orchestrator.state_machine
        assert len(orchestrator.agents) >= 0


class TestDatabase:
    """Test database models."""
    
    def test_project_guard_record(self):
        """Test project guard record."""
        from src.database import ProjectGuardRecord
        
        guard = ProjectGuardRecord("TEN-001", "PRJ-001")
        
        assert guard.partition_key == "PRJ-001"
        assert guard.type == "project_guard"
        assert guard.policy_epoch == 0
        
        doc = guard.to_dict()
        assert doc["projectId"] == "PRJ-001"
        assert doc["policyEpoch"] == 0
    
    def test_run_control_record(self):
        """Test run control record."""
        from src.database import RunControlRecord
        
        control = RunControlRecord("TEN-001", "PRJ-001", "RUN-001")
        
        assert control.state == "awaiting_scope_confirmation"
        assert control.report_revision == 1
        assert control.work_epoch == 0
        
        doc = control.to_dict()
        assert doc["runId"] == "RUN-001"
        assert doc["state"] == "awaiting_scope_confirmation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
