"""Agent orchestration framework for multi-agent research system."""

from typing import Dict, Any, Optional, List, Callable
from enum import Enum
from abc import ABC, abstractmethod
from datetime import datetime
import json
from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    """Defined agent roles in the research system."""
    PLANNER = "planner"
    SOURCE_SEARCHER = "source_searcher"
    INGESTION = "ingestion"
    RESEARCH = "research"
    SYNTHESIS = "synthesis"
    FACT_CHECKER = "fact_checker"
    CRITICAL_REVIEWER = "critical_reviewer"
    CITATION_VALIDATOR = "citation_validator"
    EVALUATOR = "evaluator"
    ORCHESTRATOR = "orchestrator"


class AgentMessage(BaseModel):
    """Message passed between agents."""
    
    schema_version: str = "1.0"
    agent_role: AgentRole
    run_id: str
    tenant_id: str
    project_id: str
    report_revision: int = 1
    message_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    output_payload: Dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"  # "pending", "processing", "completed", "failed"
    error_message: Optional[str] = None
    
    def to_queue_message(self) -> str:
        """Serialize to JSON for queue transmission."""
        data = self.model_dump(mode='json')
        return json.dumps(data)
    
    @classmethod
    def from_queue_message(cls, json_str: str) -> "AgentMessage":
        """Deserialize from JSON queue message."""
        data = json.loads(json_str)
        return cls(**data)


class Agent(ABC):
    """Base agent class."""
    
    def __init__(self, role: AgentRole, name: str):
        self.role = role
        self.name = name
        self.version = "1.0"
    
    @abstractmethod
    async def execute(self, message: AgentMessage) -> AgentMessage:
        """Execute the agent's task."""
        pass
    
    @abstractmethod
    def validate_input(self, message: AgentMessage) -> bool:
        """Validate input message format and content."""
        pass
    
    @abstractmethod
    def validate_output(self, message: AgentMessage) -> bool:
        """Validate output message format and content."""
        pass


class PlannerAgent(Agent):
    """Decomposes research questions into subquestions and queries."""
    
    def __init__(self):
        super().__init__(AgentRole.PLANNER, "Planner Agent")
    
    async def execute(self, message: AgentMessage) -> AgentMessage:
        """Decompose research request into subquestions."""
        # TODO: Call LLM to decompose question
        message.output_payload = {
            "subquestions": [],
            "search_queries": [],
            "evidence_criteria": {}
        }
        message.status = "completed"
        return message
    
    def validate_input(self, message: AgentMessage) -> bool:
        """Validate research request is present."""
        return "research_request" in message.input_payload
    
    def validate_output(self, message: AgentMessage) -> bool:
        """Validate subquestions and queries are present."""
        return all(k in message.output_payload for k in ["subquestions", "search_queries"])


class SourceSearcherAgent(Agent):
    """Searches academic APIs and web sources for evidence."""
    
    def __init__(self):
        super().__init__(AgentRole.SOURCE_SEARCHER, "Source Searcher")
    
    async def execute(self, message: AgentMessage) -> AgentMessage:
        """Search for sources matching queries."""
        # TODO: Call OpenAlex, Crossref, arXiv APIs
        message.output_payload = {
            "discovered_sources": [],
            "query_stats": {}
        }
        message.status = "completed"
        return message
    
    def validate_input(self, message: AgentMessage) -> bool:
        """Validate search queries present."""
        return "search_queries" in message.input_payload
    
    def validate_output(self, message: AgentMessage) -> bool:
        """Validate sources discovered."""
        return "discovered_sources" in message.output_payload


class IngestionAgent(Agent):
    """Ingests discovered sources into evidence store."""
    
    def __init__(self):
        super().__init__(AgentRole.INGESTION, "Ingestion Agent")
    
    async def execute(self, message: AgentMessage) -> AgentMessage:
        """Ingest sources and extract passages."""
        # TODO: Fetch content, extract passages, compute hashes
        message.output_payload = {
            "ingested_sources": [],
            "extracted_passages": [],
            "policy_violations": []
        }
        message.status = "completed"
        return message
    
    def validate_input(self, message: AgentMessage) -> bool:
        """Validate discovered sources present."""
        return "discovered_sources" in message.input_payload
    
    def validate_output(self, message: AgentMessage) -> bool:
        """Validate passages extracted."""
        return "extracted_passages" in message.output_payload


class ResearchAgent(Agent):
    """Retrieves evidence to answer research questions."""
    
    def __init__(self):
        super().__init__(AgentRole.RESEARCH, "Research Agent")
    
    async def execute(self, message: AgentMessage) -> AgentMessage:
        """Retrieve evidence for research questions."""
        # TODO: Hybrid search (keyword + semantic + vector)
        message.output_payload = {
            "retrieved_evidence": [],
            "search_metrics": {}
        }
        message.status = "completed"
        return message
    
    def validate_input(self, message: AgentMessage) -> bool:
        """Validate subquestions present."""
        return "subquestions" in message.input_payload
    
    def validate_output(self, message: AgentMessage) -> bool:
        """Validate evidence retrieved."""
        return "retrieved_evidence" in message.output_payload


class SynthesisAgent(Agent):
    """Synthesizes evidence into a draft report."""
    
    def __init__(self):
        super().__init__(AgentRole.SYNTHESIS, "Synthesis Agent")
    
    async def execute(self, message: AgentMessage) -> AgentMessage:
        """Generate draft report from evidence."""
        # TODO: Call LLM to synthesize claims from evidence
        message.output_payload = {
            "draft_report": {},
            "claims": [],
            "citation_map": {}
        }
        message.status = "completed"
        return message
    
    def validate_input(self, message: AgentMessage) -> bool:
        """Validate evidence present."""
        return "retrieved_evidence" in message.input_payload
    
    def validate_output(self, message: AgentMessage) -> bool:
        """Validate claims and report present."""
        return all(k in message.output_payload for k in ["draft_report", "claims"])


class FactCheckerAgent(Agent):
    """Independently verifies claims against evidence."""
    
    def __init__(self):
        super().__init__(AgentRole.FACT_CHECKER, "Fact Checker")
    
    async def execute(self, message: AgentMessage) -> AgentMessage:
        """Fact-check claims against evidence."""
        # TODO: Verify each claim against cited passages
        message.output_payload = {
            "findings": [],
            "verdict_summary": "pending"
        }
        message.status = "completed"
        return message
    
    def validate_input(self, message: AgentMessage) -> bool:
        """Validate claims and evidence present."""
        return all(k in message.input_payload for k in ["claims", "evidence"])
    
    def validate_output(self, message: AgentMessage) -> bool:
        """Validate findings recorded."""
        return "findings" in message.output_payload


class CriticalReviewerAgent(Agent):
    """Reviews methodology, bias, and limitations."""
    
    def __init__(self):
        super().__init__(AgentRole.CRITICAL_REVIEWER, "Critical Reviewer")
    
    async def execute(self, message: AgentMessage) -> AgentMessage:
        """Critically review research methodology."""
        # TODO: Assess methodology, omissions, bias, source quality
        message.output_payload = {
            "review_findings": [],
            "recommendations": []
        }
        message.status = "completed"
        return message
    
    def validate_input(self, message: AgentMessage) -> bool:
        """Validate report present."""
        return "draft_report" in message.input_payload
    
    def validate_output(self, message: AgentMessage) -> bool:
        """Validate review findings present."""
        return "review_findings" in message.output_payload


class AgentOrchestrator:
    """Orchestrates multi-agent execution flow."""
    
    def __init__(self):
        self.agents: Dict[AgentRole, Agent] = {}
        self.execution_history: List[AgentMessage] = []
        self.state_machine = self._build_state_machine()
    
    def register_agent(self, agent: Agent) -> None:
        """Register an agent."""
        self.agents[agent.role] = agent
    
    def _build_state_machine(self) -> Dict[str, List[AgentRole]]:
        """Define the orchestration state machine."""
        return {
            "awaiting_scope_confirmation": [AgentRole.PLANNER],
            "collecting": [AgentRole.SOURCE_SEARCHER, AgentRole.INGESTION],
            "synthesizing": [AgentRole.RESEARCH, AgentRole.SYNTHESIS],
            "reviewing": [
                AgentRole.FACT_CHECKER, 
                AgentRole.CRITICAL_REVIEWER,
                AgentRole.CITATION_VALIDATOR,
                AgentRole.EVALUATOR
            ],
            "awaiting_approval": [AgentRole.ORCHESTRATOR],
            "release_pending": [AgentRole.ORCHESTRATOR]
        }
    
    async def execute_phase(
        self, 
        current_state: str, 
        message: AgentMessage
    ) -> AgentMessage:
        """Execute all agents for a phase."""
        next_agents = self.state_machine.get(current_state, [])
        
        for agent_role in next_agents:
            if agent_role in self.agents:
                agent = self.agents[agent_role]
                
                # Validate input
                if not agent.validate_input(message):
                    message.status = "failed"
                    message.error_message = f"Invalid input for {agent.name}"
                    return message
                
                # Execute agent
                message = await agent.execute(message)
                self.execution_history.append(message)
                
                # Validate output
                if not agent.validate_output(message):
                    message.status = "failed"
                    message.error_message = f"Invalid output from {agent.name}"
                    return message
                
                if message.status == "failed":
                    return message
        
        return message
    
    def get_execution_trace(self) -> List[Dict[str, Any]]:
        """Get trace of all executed messages."""
        return [msg.model_dump(mode='json') for msg in self.execution_history]
