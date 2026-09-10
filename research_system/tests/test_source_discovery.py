"""Focused tests for the offline source discovery and ingestion slice."""

import pytest

from src.local_store import LocalStateStore
from src.models import ResearchRequest
from src.services import EvidenceService, ResearchRunService
from src.source_connectors import LocalSourceConnector


@pytest.mark.asyncio
async def test_local_connector_is_deterministic_without_network():
    connector = LocalSourceConnector()

    first = connector.search_sync("an unknown planner query")
    second = connector.search_sync("an unknown planner query")

    assert first[0].source_id == second[0].source_id
    assert first[0].url.startswith("local://")
    assert first[0].metadata["synthetic"] is True
    assert await connector.search("an unknown planner query") == second


@pytest.mark.asyncio
async def test_planner_queries_become_scoped_evidence(tmp_path):
    store = LocalStateStore(str(tmp_path / "sources.db"))
    run_service = ResearchRunService(store)
    run = await run_service.create_run(
        "TEN-1",
        "PRJ-1",
        ResearchRequest(
            title="Offline test",
            primary_question="Does intervention improve outcomes?",
            scope_description="Local fixtures only",
            max_sources=3,
        ),
    )
    evidence_service = EvidenceService(store)

    result = await evidence_service.discover_and_ingest_plan(
        "TEN-1",
        "PRJ-1",
        run.run_id,
        {"search_queries": ["intervention outcomes", "contradictory findings"]},
    )

    assert len(result["sources"]) == 2
    assert len(result["evidence"]) == 2
    assert all(item.tenant_id == "TEN-1" for item in result["sources"])
    assert all(item.run_id == run.run_id for item in result["sources"])
    assert all(item.run_id == run.run_id for item in result["evidence"])
    assert all(item.content_hash.startswith("sha256:") for item in result["evidence"])

    # A second ingestion is idempotent at the storage key/evidence ID level.
    repeated = await evidence_service.ingest_sources(
        "TEN-1", "PRJ-1", run.run_id, result["sources"]
    )
    assert [item.evidence_id for item in repeated] == [
        item.evidence_id for item in result["evidence"]
    ]
    assert await evidence_service.search_evidence(
        "TEN-1", "PRJ-1", run.run_id, "intervention"
    )


@pytest.mark.asyncio
async def test_discovery_rejects_missing_or_cross_scope_runs(tmp_path):
    store = LocalStateStore(str(tmp_path / "scope.db"))
    run_service = ResearchRunService(store)
    run = await run_service.create_run(
        "TEN-1",
        "PRJ-1",
        ResearchRequest(
            title="Scope test",
            primary_question="Question",
            scope_description="Local fixtures",
        ),
    )
    service = EvidenceService(store)
    connector = LocalSourceConnector()
    source = (await connector.search("question"))[0]
    source = source.model_copy(update={"tenant_id": "TEN-OTHER"})

    assert await service.discover_sources(
        "TEN-OTHER", "PRJ-1", run.run_id, ["question"]
    ) == []
    assert await service.ingest_sources(
        "TEN-1", "PRJ-1", run.run_id, [source]
    ) == []
    assert await service.discover_sources(
        "TEN-1", "PRJ-1", "RUN-MISSING", ["question"]
    ) == []
