"""Offline tests for FTS5/BM25, local embeddings, hybrid and contradictory search."""

from datetime import datetime

import pytest

from src.local_store import LocalStateStore
from src.models import (
    EligibilityStatus,
    EvidenceRecord,
    PeerReviewStatus,
    SourceType,
    SourceUseDecision,
)
from src.retrieval import (
    build_contradictory_queries,
    build_fts_query,
    cosine,
    embed_text,
    reciprocal_rank_fusion,
)
from src.services import EvidenceService


def _evidence(evidence_id, title, passage, run_id="RUN-1", decision="allowed"):
    return EvidenceRecord(
        tenant_id="TEN-1",
        project_id="PRJ-1",
        run_id=run_id,
        report_revision=1,
        evidence_id=evidence_id,
        source_id=f"SRC-{evidence_id}",
        source_type=SourceType.PAPER,
        title=title,
        url=f"https://example.org/{evidence_id}",
        retrieved_at=datetime(2026, 1, 1),
        peer_review_status=PeerReviewStatus.PEER_REVIEWED,
        passage=passage,
        content_hash=f"sha256:{evidence_id}",
        source_use_decision=SourceUseDecision(decision),
        eligibility_status=EligibilityStatus.ELIGIBLE,
        policy_version="test",
    )


async def _service(tmp_path, records):
    store = LocalStateStore(str(tmp_path / "retrieval.db"))
    service = EvidenceService(store)
    for record in records:
        await service.index_evidence("TEN-1", "PRJ-1", record.run_id, [record])
    return service


def test_fts_query_quotes_terms_so_operators_cannot_inject():
    assert build_fts_query('AND "x" NOT near(') == '"and" OR "not" OR "near"'
    assert build_fts_query("!!") == ""


def test_contradictory_queries_keep_topic_and_add_negation():
    queries = build_contradictory_queries("Statins reduce risk")
    assert queries and all(
        q.startswith('("statins" OR "reduce" OR "risk") AND "') for q in queries
    )
    assert build_contradictory_queries("  ") == []


def test_embedding_is_deterministic_and_similarity_orders_sensibly():
    a = embed_text("deep learning for protein folding")
    assert a == embed_text("deep learning for protein folding")
    close = cosine(a, embed_text("protein folding with deep learning"))
    far = cosine(a, embed_text("medieval trade routes in the Baltic"))
    assert close > far


def test_rrf_rewards_agreement_between_rankings():
    fused = reciprocal_rank_fusion([(1.0, ["a", "b", "c"]), (1.0, ["b", "c", "d"])])
    assert [item for item, _ in fused][0] == "b"


@pytest.mark.asyncio
async def test_bm25_prefers_title_and_term_density(tmp_path):
    service = await _service(
        tmp_path,
        [
            _evidence("E1", "Gardening notes", "A short mention of quantum computing."),
            _evidence("E2", "Quantum computing advances", "Quantum computing hardware."),
            _evidence("E3", "Cooking", "Nothing relevant here."),
        ],
    )

    found = await service.search_evidence(
        "TEN-1", "PRJ-1", "RUN-1", "quantum computing", search_type="keyword"
    )

    assert [r.evidence_id for r in found] == ["E2", "E1"]


@pytest.mark.asyncio
async def test_search_is_scoped_to_run_and_allowed_sources(tmp_path):
    service = await _service(
        tmp_path,
        [
            _evidence("E1", "Solar panel efficiency", "Efficiency of solar panels."),
            _evidence("E2", "Solar panel efficiency", "Other run.", run_id="RUN-2"),
            _evidence("E3", "Solar panel efficiency", "Blocked.", decision="blocked"),
        ],
    )

    for mode in ("keyword", "semantic", "hybrid"):
        found = await service.search_evidence(
            "TEN-1", "PRJ-1", "RUN-1", "solar panel efficiency", search_type=mode
        )
        assert [r.evidence_id for r in found] == ["E1"], mode


@pytest.mark.asyncio
async def test_reindexing_replaces_fts_row(tmp_path):
    service = await _service(
        tmp_path, [_evidence("E1", "Alpha topic", "alpha alpha alpha")]
    )
    await service.index_evidence(
        "TEN-1", "PRJ-1", "RUN-1", [_evidence("E1", "Beta topic", "beta beta")]
    )

    assert not await service.search_evidence(
        "TEN-1", "PRJ-1", "RUN-1", "alpha", search_type="keyword"
    )
    assert await service.search_evidence(
        "TEN-1", "PRJ-1", "RUN-1", "beta", search_type="keyword"
    )


@pytest.mark.asyncio
async def test_existing_evidence_is_backfilled_into_fts(tmp_path):
    store = LocalStateStore(str(tmp_path / "legacy.db"))
    record = _evidence("E1", "Legacy paper", "pre-FTS evidence about graphene")
    store.put("evidence", "TEN-1", "PRJ-1", "E1", record.model_dump(mode="json"))
    with store._connect() as connection:
        connection.execute("DELETE FROM evidence_fts")

    reopened = EvidenceService(LocalStateStore(str(tmp_path / "legacy.db")))
    found = await reopened.search_evidence(
        "TEN-1", "PRJ-1", "RUN-1", "graphene", search_type="keyword"
    )

    assert [r.evidence_id for r in found] == ["E1"]


@pytest.mark.asyncio
async def test_contradictory_search_surfaces_negative_findings(tmp_path):
    service = await _service(
        tmp_path,
        [
            _evidence("E1", "Vitamin D supplementation", "Vitamin D improves bone density."),
            _evidence(
                "E2",
                "Vitamin D trial",
                "Vitamin D supplementation had no effect and failed to replicate.",
            ),
        ],
    )

    found = await service.search_evidence(
        "TEN-1", "PRJ-1", "RUN-1", "vitamin D supplementation",
        search_type="contradictory",
    )

    assert found[0].evidence_id == "E2"


@pytest.mark.asyncio
async def test_unknown_search_type_is_rejected(tmp_path):
    service = await _service(tmp_path, [])
    with pytest.raises(ValueError):
        await service.search_evidence("TEN-1", "PRJ-1", "RUN-1", "x", search_type="bogus")
