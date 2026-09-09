# Implementation Guide for Multi-Agent Research System

## Phase Overview

This guide provides step-by-step instructions for completing the implementation of the multi-agent research system based on the specification.

## Table of Contents

1. [Phase 1: Infrastructure Setup](#phase-1-infrastructure-setup)
2. [Phase 2: Core Agent Implementation](#phase-2-core-agent-implementation)
3. [Phase 3: Source Discovery & Ingestion](#phase-3-source-discovery--ingestion)
4. [Phase 4: Search & Retrieval](#phase-4-search--retrieval)
5. [Phase 5: Review Pipeline](#phase-5-review-pipeline)
6. [Phase 6: Release & Publication](#phase-6-release--publication)
7. [Testing Strategy](#testing-strategy)

---

## Phase 1: Infrastructure Setup

### 1.1 Azure Resources

Create the following Azure resources:

#### Cosmos DB
```bicep
resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  name: 'research-cosmos-${environment().authentication.loginEndpoint}'
  location: resourceGroup().location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: resourceGroup().location
        failoverPriority: 0
      }
    ]
  }
}
```

Create database and container:
- Database: `research_db`
- Container: `documents`
  - Partition Key: `/partitionKey`
  - TTL: -1 (no expiration)
  - Unique keys: `[tenantId, projectId, runId]` combinations

#### Azure AI Search
```bicep
resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: 'research-search'
  location: resourceGroup().location
  sku: {
    name: 'standard'
  }
}
```

Create index `evidence-index` with fields:
- `id` (Edm.String, key)
- `passageText` (Edm.String, searchable)
- `sourceType` (Edm.String, filterable)
- `sourceUrl` (Edm.String)
- `vectorizedPassage` (Collection(Edm.Single), vector search)
- `tenantId` (Edm.String, filterable)
- `projectId` (Edm.String, filterable)
- `evidenceId` (Edm.String, filterable)

#### Blob Storage
```bicep
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'researchstorage${uniqueString(resourceGroup().id)}'
  location: resourceGroup().location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
}
```

Create containers:
- `evidence` - Original source documents
- `artifacts` - Generated reports and manifests

#### Service Bus
```bicep
resource serviceBus 'Microsoft.ServiceBus/namespaces@2023-01-01-preview' = {
  name: 'research-bus'
  location: resourceGroup().location
  sku: {
    name: 'Standard'
  }
}
```

Create queue: `research-tasks` with auto-forwarding to dead letter after 5 retries.

### 1.2 Database Schema

In `src/database.py`, implement Cosmos DB initialization:

```python
async def init_cosmos_db():
    """Initialize Cosmos DB database and containers."""
    from azure.cosmos.aio import CosmosClient
    from src.config import get_azure_config
    
    config = get_azure_config()
    async with CosmosClient(config.cosmos_endpoint, credential=default_azure_credential()) as client:
        # Create/get database
        database = client.get_database_client(config.cosmos_db_name)
        
        # Create container for project isolation
        container = database.create_container_if_not_exists(
            id=config.cosmos_container_name,
            partition_key="/partitionKey",
            indexing_policy={
                "indexingMode": "consistent",
                "includedPaths": [
                    {"path": "/*"}
                ],
                "excludedPaths": [
                    {"path": "/\"_etag\"/?"}
                ]
            },
            unique_keys=[
                {"paths": ["/tenantId", "/projectId", "/runId", "/id"]}
            ]
        )
        return database
```

### 1.3 Authentication & Authorization

Update `src/config.py` to use Azure AD:

```python
from azure.identity.aio import DefaultAzureCredential

async def get_credential():
    """Get Azure credential for identity-based authentication."""
    return DefaultAzureCredential(
        exclude_interactive_browser_auth=True,
        exclude_shared_token_cache_credential=True
    )
```

---

## Phase 2: Core Agent Implementation

### 2.1 PlannerAgent

Implement `src/agents.py` PlannerAgent.execute():

```python
async def execute(self, message: AgentMessage) -> AgentMessage:
    """Decompose research request into subquestions."""
    from src.config import get_model_config
    from openai import AsyncAzureOpenAI
    
    config = get_model_config()
    client = AsyncAzureOpenAI()
    
    research_request = message.input_payload["research_request"]
    
    prompt = f"""Analyze this research request and decompose it into 3-5 specific subquestions.
    
    Title: {research_request.title}
    Question: {research_request.primary_question}
    Scope: {research_request.scope_description}
    
    Return JSON:
    {{
        "subquestions": ["subq1", "subq2", ...],
        "search_queries": ["query1", "query2", ...],
        "evidence_criteria": {{
            "required_source_types": [...],
            "min_publication_date": "YYYY-MM-DD",
            "peer_review_preferred": true
        }}
    }}"""
    
    response = await client.chat.completions.create(
        model=config.openai_deployment_id,
        messages=[{"role": "user", "content": prompt}],
        temperature=config.openai_temperature,
        max_tokens=config.openai_max_tokens
    )
    
    import json
    output = json.loads(response.choices[0].message.content)
    message.output_payload = output
    message.status = "completed"
    return message
```

### 2.2 ResearchAgent

Implement evidence retrieval:

```python
async def execute(self, message: AgentMessage) -> AgentMessage:
    """Retrieve evidence for subquestions."""
    from src.services import EvidenceService
    
    evidence_service = EvidenceService()
    
    subquestions = message.input_payload["subquestions"]
    retrieved_evidence = []
    
    for subq in subquestions:
        # Perform hybrid search
        results = await evidence_service.search_evidence(
            message.tenant_id,
            message.project_id,
            message.run_id,
            query=subq,
            search_type="hybrid"
        )
        retrieved_evidence.extend(results)
    
    message.output_payload = {
        "retrieved_evidence": [e.model_dump(mode='json') for e in retrieved_evidence],
        "search_metrics": {"total_results": len(retrieved_evidence)}
    }
    message.status = "completed"
    return message
```

### 2.3 SynthesisAgent

Implement report generation:

```python
async def execute(self, message: AgentMessage) -> AgentMessage:
    """Generate draft report from evidence."""
    from src.config import get_model_config
    from openai import AsyncAzureOpenAI
    import json
    
    config = get_model_config()
    client = AsyncAzureOpenAI()
    
    evidence = message.input_payload["retrieved_evidence"]
    research_request = message.input_payload.get("research_request")
    
    # Prepare evidence context
    evidence_text = "\n".join([
        f"[{e.get('evidenceId', 'unknown')}] {e.get('passage', '')}"
        for e in evidence[:10]  # Limit to avoid token limits
    ])
    
    prompt = f"""Write a research report addressing: {research_request.get('primary_question')}
    
    Based on this evidence:
    {evidence_text}
    
    Generate JSON with:
    {{
        "draft_report": {{
            "title": "...",
            "abstract": "...",
            "conclusions": "...",
            "limitations": []
        }},
        "claims": [
            {{
                "id": "CLM-001",
                "text": "...",
                "material": true,
                "evidence_ids": ["evidence-123"]
            }}
        ]
    }}"""
    
    response = await client.chat.completions.create(
        model=config.openai_deployment_id,
        messages=[{"role": "user", "content": prompt}],
        temperature=config.openai_temperature,
        max_tokens=config.openai_max_tokens
    )
    
    output = json.loads(response.choices[0].message.content)
    message.output_payload = output
    message.status = "completed"
    return message
```

---

## Phase 3: Source Discovery & Ingestion

### 3.1 OpenAlex Connector

Create `src/connectors/openalex.py`:

```python
"""OpenAlex API connector for academic paper discovery."""

import httpx
from typing import List, Dict, Any

class OpenAlexConnector:
    """Discover papers from OpenAlex."""
    
    BASE_URL = "https://api.openalex.org"
    
    async def search(
        self,
        query: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search OpenAlex for papers."""
        async with httpx.AsyncClient() as client:
            params = {
                "search": query,
                "per_page": 50
            }
            
            if date_from:
                params["from_publication_date"] = date_from
            if date_to:
                params["to_publication_date"] = date_to
            
            response = await client.get(
                f"{self.BASE_URL}/works",
                params=params
            )
            response.raise_for_status()
            
            works = response.json()["results"]
            
            return [{
                "title": w["title"],
                "url": w["doi"],
                "doi": w["doi"],
                "authors": [a["author"]["display_name"] for a in w.get("authorships", [])],
                "published_at": w.get("publication_date"),
                "peer_review_status": "peer-reviewed"
            } for w in works]
```

### 3.2 Web Crawler

Create `src/crawlers/web_crawler.py`:

```python
"""Governed web crawler with robots.txt compliance."""

import httpx
from urllib.robotparser import RobotFileParser
from typing import Optional, List

class GovernedWebCrawler:
    """Crawl permitted public websites."""
    
    def __init__(self, rate_limit: int = 5):
        """Initialize crawler with rate limit (req/min per domain)."""
        self.rate_limit = rate_limit
        self.robot_parsers = {}
    
    async def can_fetch(self, url: str) -> bool:
        """Check if URL can be fetched per robots.txt."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc
        
        if domain not in self.robot_parsers:
            rp = RobotFileParser()
            rp.set_url(f"{parsed.scheme}://{domain}/robots.txt")
            try:
                await asyncio.to_thread(rp.read)
            except:
                return True  # No robots.txt, allow
            self.robot_parsers[domain] = rp
        
        return self.robot_parsers[domain].can_fetch("*", url)
    
    async def fetch(self, url: str) -> Optional[str]:
        """Fetch webpage content."""
        if not await self.can_fetch(url):
            return None
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
            except:
                return None
```

### 3.3 Content Extraction

Create `src/parsers/content_extractor.py`:

```python
"""Extract and preserve content structure from HTML and PDF."""

from typing import List, Dict, Any
import pymupdf
from trafilatura import extract
from bs4 import BeautifulSoup

class ContentExtractor:
    """Extract passages from various document formats."""
    
    async def extract_from_html(self, html: str) -> List[Dict[str, Any]]:
        """Extract passages from HTML while preserving structure."""
        from trafilatura import extract
        
        # Extract main content
        content = extract(html, include_comments=False)
        
        # Parse structure
        soup = BeautifulSoup(html, 'html.parser')
        passages = []
        
        for section in soup.find_all(['h2', 'h3', 'p']):
            if section.name.startswith('h'):
                heading = section.get_text(strip=True)
            elif section.name == 'p':
                passages.append({
                    "section": heading if 'heading' in locals() else "Introduction",
                    "passage": section.get_text(strip=True),
                    "type": "paragraph"
                })
        
        return passages
    
    async def extract_from_pdf(self, file_path: str) -> List[Dict[str, Any]]:
        """Extract passages from PDF with page and position info."""
        passages = []
        
        doc = pymupdf.open(file_path)
        
        for page_num, page in enumerate(doc, 1):
            text = page.get_text()
            
            # Split by paragraphs
            for para in text.split("\n\n"):
                if len(para.strip()) > 50:
                    passages.append({
                        "page": page_num,
                        "passage": para.strip(),
                        "type": "paragraph"
                    })
        
        return passages
```

---

## Phase 4: Search & Retrieval

### 4.1 Hybrid Search Implementation

Update `src/services.py` EvidenceService:

```python
async def search_evidence(
    self,
    tenant_id: str,
    project_id: str,
    run_id: str,
    query: str,
    search_type: str = "hybrid"
) -> List[EvidenceRecord]:
    """Hybrid search combining keyword, semantic, and vector."""
    from azure.search.documents.aio import SearchClient
    from openai import AsyncAzureOpenAI
    
    search_client = SearchClient(...)
    openai_client = AsyncAzureOpenAI()
    
    if search_type in ["hybrid", "semantic"]:
        # Generate query embedding
        embedding_response = await openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=query
        )
        query_vector = embedding_response.data[0].embedding
    
    # Build search filters for project isolation
    filters = f"tenantId eq '{tenant_id}' and projectId eq '{project_id}'"
    
    if search_type == "keyword":
        results = await search_client.search(
            search_text=query,
            filter=filters
        )
    elif search_type == "hybrid":
        results = await search_client.search(
            search_text=query,
            vector_queries=[{
                "vector": query_vector,
                "k_nearest_neighbors": 50,
                "fields": "vectorizedPassage"
            }],
            filter=filters,
            query_type="semantic"
        )
    
    return [EvidenceRecord(**hit) for hit in results]
```

### 4.2 Relevance Ranking

Add ranking to search results:

```python
def rank_results(
    results: List[EvidenceRecord],
    query: str,
    weights: Dict[str, float]
) -> List[EvidenceRecord]:
    """Rank results by multiple relevance signals."""
    from datetime import datetime, timedelta
    
    scored_results = []
    
    for result in results:
        score = 0.0
        
        # Keyword match score
        if query.lower() in result.passage.lower():
            score += weights.get("keyword", 0.3) * 1.0
        
        # Recency score (prefer recent publications)
        if result.published_at:
            days_old = (datetime.utcnow() - result.published_at).days
            recency = max(0, 1 - (days_old / 1825))  # 5-year decay
            score += weights.get("recency", 0.2) * recency
        
        # Peer review score
        if result.peer_review_status == "peer-reviewed":
            score += weights.get("peer_review", 0.3)
        
        scored_results.append((result, score))
    
    return [r[0] for r in sorted(scored_results, key=lambda x: x[1], reverse=True)]
```

---

## Phase 5: Review Pipeline

### 5.1 Fact-Checker Implementation

Create `src/reviewers/fact_checker.py`:

```python
"""Independent fact-checking agent."""

class FactChecker:
    """Verify claims against evidence."""
    
    async def check_claim(
        self,
        claim: ClaimRecord,
        evidence_records: List[EvidenceRecord]
    ) -> ReviewFinding:
        """Verify a claim against its cited evidence."""
        from openai import AsyncAzureOpenAI
        import json
        
        client = AsyncAzureOpenAI()
        
        # Prepare evidence context
        evidence_text = "\n".join([
            f"[{e.evidence_id}] {e.passage}"
            for e in evidence_records
        ])
        
        prompt = f"""Fact-check this claim against the provided evidence:
        
        Claim: {claim.text}
        
        Evidence:
        {evidence_text}
        
        Is the claim supported, contradicted, or insufficiently supported?
        
        Return JSON:
        {{
            "verdict": "supported|contradicted|insufficient_evidence",
            "explanation": "...",
            "supporting_passages": [],
            "contradicting_passages": []
        }}"""
        
        response = await client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        
        result = json.loads(response.choices[0].message.content)
        
        return ReviewFinding(
            finding_id=f"FND-{uuid.uuid4().hex[:8]}",
            claim_id=claim.claim_id,
            verdict=result["verdict"],
            explanation=result["explanation"],
            severity="high" if result["verdict"] == "contradicted" else "info"
        )
```

### 5.2 Critical Reviewer

Create `src/reviewers/critical_reviewer.py`:

```python
"""Critical methodology and bias assessment."""

class CriticalReviewer:
    """Review research methodology and limitations."""
    
    async def review_report(
        self,
        draft_report,
        evidence_set: List[EvidenceRecord]
    ) -> List[ReviewFinding]:
        """Critically review report methodology."""
        from openai import AsyncAzureOpenAI
        
        client = AsyncAzureOpenAI()
        
        prompt = f"""Critically review this research report:
        
        {draft_report.model_dump_json(indent=2)}
        
        Assess:
        1. Methodology soundness
        2. Potential biases
        3. Source quality and independence
        4. Limitations and alternative explanations
        5. Gaps in evidence
        
        Return JSON:
        {{
            "findings": [
                {{
                    "category": "methodology|bias|source_quality|alternative_explanations|evidence_gaps",
                    "severity": "warning|high|critical",
                    "finding": "...",
                    "recommendation": "..."
                }}
            ]
        }}"""
        
        response = await client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        
        import json
        result = json.loads(response.choices[0].message.content)
        
        findings = []
        for f in result["findings"]:
            findings.append(ReviewFinding(
                finding_id=f"FND-{uuid.uuid4().hex[:8]}",
                category=f["category"],
                severity=f["severity"],
                explanation=f["finding"],
                required_action=f["recommendation"]
            ))
        
        return findings
```

---

## Phase 6: Release & Publication

### 6.1 ADR-015 Release Protocol

Implement in `src/services.py`:

```python
async def commit_release(
    self,
    tenant_id: str,
    project_id: str,
    run_id: str,
    approval_record: ApprovalRecord
) -> Optional[ReleaseRecord]:
    """Implement ADR-015 cross-service release protocol."""
    from azure.cosmos.exceptions import CosmosHttpResponseError
    
    # Step 1: Prepare artifacts (already done in prepare_release)
    
    # Step 2: Conditional Cosmos write with all invariants
    try:
        # Get current run control record
        run_control = await self._get_run_control(
            tenant_id, project_id, run_id
        )
        
        # Verify invariants
        assert run_control.state == "approved"
        assert run_control.approval_reference == approval_record.approval_id
        assert approval_record.validity == True
        
        # Prepare release record
        release = ReleaseRecord(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            release_id=f"REL-{uuid.uuid4().hex[:8]}",
            released_at=datetime.utcnow(),
            approval_reference=approval_record.approval_id
        )
        
        # Atomic transaction in Cosmos
        async with self.cosmos_client.get_database_client(
            get_azure_config().cosmos_db_name
        ).get_container_client(
            get_azure_config().cosmos_container_name
        ) as container:
            # Conditional update on ETag
            run_control.state = "released"
            run_control.release_marker = release.release_id
            
            await container.replace_item(
                run_control.id,
                run_control.to_dict(),
                match_condition=MatchConditions.IfNotModified,
                etag=run_control.e_tag
            )
            
            # Create release record
            await container.create_item(release.model_dump(mode='json'))
            
            # Create audit record
            audit = AuditRecord(
                tenant_id, project_id, "report_released", approval_record.approver_id
            )
            audit.details = {"release_id": release.release_id}
            await container.create_item(audit.to_dict())
            
            # Dispatch outbox event
            outbox = OutboxRecord(
                tenant_id, project_id, "report_published"
            )
            outbox.payload = release.model_dump(mode='json')
            await container.create_item(outbox.to_dict())
        
        return release
        
    except CosmosHttpResponseError as e:
        if e.status_code == 412:  # Precondition failed (ETag mismatch)
            # Stale approval or concurrent update
            raise HTTPException(
                status_code=409,
                detail="Release failed: concurrent modification or stale approval"
            )
        raise
```

### 6.2 Withdrawal Procedure

```python
async def withdraw_release(
    self,
    tenant_id: str,
    project_id: str,
    release_id: str,
    reason: str,
    withdrawn_by: str
) -> bool:
    """Withdraw a published release."""
    
    async with self.cosmos_client.get_database_client(...) as db:
        container = db.get_container_client(...)
        
        # Atomically update release and create audit
        release = await container.read_item(release_id, partition_key=project_id)
        release["is_withdrawn"] = True
        release["withdrawal_reason"] = reason
        release["withdrawn_at"] = datetime.utcnow().isoformat()
        release["withdrawn_by"] = withdrawn_by
        
        await container.replace_item(release_id, release)
        
        # Invalidate caches
        await self._invalidate_release_cache(release_id)
        
        # Dispatch withdrawal event
        outbox = OutboxRecord(tenant_id, project_id, "report_withdrawn")
        outbox.payload = {
            "release_id": release_id,
            "reason": reason
        }
        await container.create_item(outbox.to_dict())
        
        return True
```

---

## Testing Strategy

### Unit Tests

Create `tests/test_models.py`:

```python
def test_run_record_creation():
    """Test run record initialization."""
    req = ResearchRequest(
        title="Test", primary_question="Q?", scope_description="S"
    )
    run = RunRecord(
        tenant_id="TEN-001",
        project_id="PRJ-001",
        run_id="RUN-001",
        research_request=req,
        state=RunState.AWAITING_SCOPE_CONFIRMATION,
        configuration_snapshot_id="CFG-001",
        policy_epoch=0,
        start_time=datetime.utcnow(),
        updated_time=datetime.utcnow()
    )
    
    assert run.state == RunState.AWAITING_SCOPE_CONFIRMATION
    assert run.report_revision == 1
```

### Integration Tests

Create `tests/test_services.py`:

```python
@pytest.mark.asyncio
async def test_create_research_run():
    """Test end-to-end run creation."""
    service = ResearchRunService()
    
    request = ResearchRequest(
        title="Climate Impact Study",
        primary_question="What is the impact of climate change?",
        scope_description="Focus on recent studies (2020-2024)",
    )
    
    run = await service.create_run("TEN-001", "PRJ-001", request)
    
    assert run.run_id.startswith("RUN-")
    assert run.state == RunState.AWAITING_SCOPE_CONFIRMATION
```

### API Tests

Create `tests/test_api.py`:

```python
@pytest.mark.asyncio
async def test_create_project_endpoint(client):
    """Test project creation API."""
    response = client.post(
        "/api/v1/projects?tenant_id=TEN-001",
        json={
            "name": "Climate Research",
            "description": "Global climate studies",
            "max_budget_usd": 100.0
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "project" in data
    assert data["project"]["project_id"].startswith("PRJ-")
```

---

## Deployment Checklist

- [ ] Azure resources created (Cosmos DB, Blob Storage, AI Search, Service Bus)
- [ ] Environment variables configured
- [ ] Database schema initialized
- [ ] Authentication with Azure AD implemented
- [ ] All agents implemented and tested
- [ ] Search and retrieval working
- [ ] Review pipeline functional
- [ ] Release workflow implemented (ADR-015)
- [ ] API endpoints tested
- [ ] Error handling and retry logic complete
- [ ] Monitoring and telemetry configured
- [ ] Security review completed
- [ ] Load testing passed
- [ ] Production deployment plan finalized

---

## Success Criteria

1. **Functional:** All agents execute successfully, end-to-end research workflow completes
2. **Correctness:** Evidence citations are accurate, claims grounded in retrieved passages
3. **Security:** Project isolation enforced, no cross-tenant data leakage
4. **Reliability:** ADR-015 invariants maintained, recovery from failures
5. **Performance:** API responds <500ms, search <1s, synthesis <30s
6. **Audit:** Complete audit trail for all operations
7. **Compliance:** Meets all specification requirements

---

For questions or issues, refer to the main specification document and ADR records for design rationale.
