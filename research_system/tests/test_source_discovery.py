"""Focused tests for the offline source discovery and ingestion slice."""

import pytest

from src.local_store import LocalStateStore
from src.models import PeerReviewStatus, ResearchRequest, SourceType
from src.services import EvidenceService, ResearchRunService, source_passes_governance
from src.evidence_extraction import ExtractionError, chunk_text, fetch_document
from src.source_connectors import (
    ArxivConnector,
    CrossrefConnector,
    LocalSourceConnector,
    OpenAlexConnector,
    SourceRecord,
)


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
    assert all(item.source_snapshot_id for item in result["evidence"])
    assert all(item.passage_id for item in result["evidence"])

    snapshots = store.list("source_snapshot", "TEN-1", "PRJ-1", limit=10)
    passages = store.list("passage", "TEN-1", "PRJ-1", limit=10)
    assert len(snapshots) == 2
    assert len(passages) == 2

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


@pytest.mark.asyncio
async def test_discovery_deduplicates_sources_by_doi(tmp_path):
    class DuplicateConnector:
        name = "duplicate"

        async def search(self, query, *, limit=20, date_range_start=None, date_range_end=None):
            return [
                SourceRecord(
                    source_id="DUP-1",
                    connector="duplicate",
                    title="Same paper from provider A",
                    url="https://example.test/a",
                    source_type=SourceType.PAPER,
                    abstract="First abstract about reliable evidence.",
                    doi="10.1234/SAME",
                    authors=["A"],
                    peer_review_status=PeerReviewStatus.UNKNOWN,
                ),
                SourceRecord(
                    source_id="DUP-2",
                    connector="duplicate",
                    title="Same paper from provider B",
                    url="https://example.test/b",
                    source_type=SourceType.PAPER,
                    abstract="Second abstract about reliable evidence.",
                    doi="https://doi.org/10.1234/same",
                    authors=["B"],
                    peer_review_status=PeerReviewStatus.UNKNOWN,
                ),
            ]

    store = LocalStateStore(str(tmp_path / "dedup.db"))
    run_service = ResearchRunService(store)
    run = await run_service.create_run(
        "TEN-1",
        "PRJ-1",
        ResearchRequest(
            title="Dedup test",
            primary_question="Do duplicate providers collapse?",
            scope_description="Dedup",
            max_sources=10,
        ),
    )
    service = EvidenceService(store, connector=DuplicateConnector())

    result = await service.discover_and_ingest_plan(
        "TEN-1", "PRJ-1", run.run_id, {"search_queries": ["duplicates"]}
    )

    assert len(result["sources"]) == 1
    assert len(result["evidence"]) == 1
    assert result["sources"][0].metadata["canonical_source_id"].startswith("CAN-DOI-")


def test_openalex_connector_maps_work_to_source(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "doi": "https://doi.org/10.1234/example",
                        "display_name": "Recent advances in AI agents",
                        "type": "article",
                        "publication_date": "2026-08-15",
                        "publication_year": 2026,
                        "cited_by_count": 12,
                        "abstract_inverted_index": {
                            "AI": [0],
                            "agents": [1],
                            "coordinate": [2],
                            "tools": [3],
                        },
                        "authorships": [
                            {"author": {"display_name": "Ada Lovelace"}},
                            {"author": {"display_name": "Grace Hopper"}},
                        ],
                        "primary_location": {
                            "landing_page_url": "https://example.org/paper",
                            "source": {"display_name": "Journal of AI"},
                        },
                        "open_access": {"license": "cc-by"},
                    }
                ]
            }

    def fake_get(url, params, timeout, headers):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        captured["headers"] = headers
        return Response()

    monkeypatch.setattr("src.source_connectors.requests.get", fake_get)

    connector = OpenAlexConnector(
        base_url="https://api.openalex.org",
        mailto="researcher@example.test",
        latest_query_days=90,
    )

    sources = connector.search_sync("latest on AI", limit=5)

    assert captured["url"] == "https://api.openalex.org/works"
    assert captured["params"]["search"] == "latest on AI"
    assert captured["params"]["sort"] == "publication_date:desc"
    assert "from_publication_date:" in captured["params"]["filter"]
    assert sources[0].connector == "openalex"
    assert sources[0].source_id.startswith("OPENALEX-")
    assert sources[0].title == "Recent advances in AI agents"
    assert sources[0].doi == "10.1234/example"
    assert sources[0].authors == ["Ada Lovelace", "Grace Hopper"]
    assert sources[0].passage == "AI agents coordinate tools"
    assert sources[0].metadata["source_display_name"] == "Journal of AI"


def test_crossref_connector_maps_work_and_filters(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"items": [{
                "DOI": "10.1234/example", "URL": "https://doi.org/10.1234/example",
                "title": ["A Crossref paper"], "abstract": "<jats:p>Useful &amp; clear.</jats:p>",
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "published": {"date-parts": [[2026, 8, 15]]},
                "type": "journal-article", "container-title": ["Journal"],
                "publisher": "Publisher", "is-referenced-by-count": 4,
                "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
            }]}}

    def fake_get(url, params, timeout, headers):
        captured.update(url=url, params=params, headers=headers)
        return Response()

    monkeypatch.setattr("src.source_connectors.requests.get", fake_get)
    result = CrossrefConnector(mailto="researcher@example.test").search_sync(
        "methods", limit=3, date_range_start=__import__("datetime").datetime(2026, 1, 1),
        date_range_end=__import__("datetime").datetime(2026, 12, 31),
    )
    assert captured["url"].endswith("/works")
    assert captured["params"] == {
        "query": "methods", "rows": 3, "mailto": "researcher@example.test",
        "filter": "from-pub-date:2026-01-01,until-pub-date:2026-12-31",
    }
    assert result[0].abstract == "Useful & clear."
    assert result[0].authors == ["Ada Lovelace"]
    assert result[0].peer_review_status == PeerReviewStatus.PEER_REVIEWED


def test_arxiv_connector_maps_and_filters_atom(monkeypatch):
    class Response:
        text = """<feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry><id>http://arxiv.org/abs/2401.12345v2</id>
          <title>  An arXiv title </title><summary> An abstract. </summary>
          <published>2026-08-15T00:00:00Z</published>
          <author><name>Ada Lovelace</name></author>
          <category term="cs.AI"/><arxiv:primary_category term="cs.AI"/>
          <arxiv:doi>10.48550/arXiv.2401.12345</arxiv:doi>
          <link rel="alternate" href="http://arxiv.org/abs/2401.12345"/>
          <link title="pdf" href="http://arxiv.org/pdf/2401.12345.pdf"/>
          </entry></feed>"""

        def raise_for_status(self):
            return None

    monkeypatch.setattr("src.source_connectors.requests.get", lambda *args, **kwargs: Response())
    result = ArxivConnector().search_sync(
        "AI", date_range_start=__import__("datetime").datetime(2026, 1, 1),
        date_range_end=__import__("datetime").datetime(2026, 12, 31),
    )
    assert result[0].metadata["arxiv_id"] == "2401.12345"
    assert result[0].doi == "10.48550/arXiv.2401.12345"
    assert result[0].authors == ["Ada Lovelace"]
    assert result[0].metadata["pdf_url"].endswith(".pdf")


def test_source_governance_enforces_domains_and_licenses():
    source = SourceRecord(
        source_id="GOV-1",
        connector="test",
        title="Permitted source",
        url="https://papers.example.org/article",
        license="https://creativecommons.org/licenses/by/4.0/",
    )
    assert source_passes_governance(
        source,
        approved_domains=["example.org"],
        allowed_licenses=["cc-by"],
        require_permissive_license=True,
    )
    assert not source_passes_governance(
        source, excluded_domains=["papers.example.org"], allowed_licenses=["cc-by"]
    )


def test_html_extraction_and_chunk_deduplication(monkeypatch):
    class Response:
        content = b"<html><body><h1>Title</h1><p>First paragraph.</p><script>bad()</script><p>Second paragraph.</p></body></html>"
        headers = {"Content-Type": "text/html"}

        def raise_for_status(self):
            return None

    source = SourceRecord(
        source_id="HTML-1",
        connector="test",
        title="HTML",
        url="https://open.example/article",
        license="cc-by",
    )
    monkeypatch.setattr("src.evidence_extraction._download", lambda *args: (
        Response.content, Response.headers, source.url))
    document = fetch_document(source, approved_domains=["open.example"])
    assert document.media_type == "text/html"
    chunks = chunk_text("One paragraph.\n\nOne paragraph.\n\nA longer second paragraph.", max_chars=40, overlap_chars=5)
    assert len(chunks) == 2
    assert "bad" not in document.text


def test_document_policy_rejects_unapproved_url():
    source = SourceRecord(
        source_id="HTML-2", connector="test", title="HTML",
        url="https://paywalled.example/article", license="cc-by",
    )
    with pytest.raises(ExtractionError):
        fetch_document(source, approved_domains=["open.example"])
    assert not source_passes_governance(
        source, approved_domains=["other.example"], allowed_licenses=["cc-by"]
    )
    assert not source_passes_governance(
        source,
        approved_domains=["example.org"],
        allowed_licenses=["cc0"],
        require_permissive_license=True,
    )


@pytest.mark.asyncio
async def test_openalex_sources_become_searchable_paper_evidence(tmp_path, monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W456",
                        "display_name": "AI evaluation trends in 2026",
                        "type": "article",
                        "publication_date": "2026-07-01",
                        "abstract_inverted_index": {
                            "Evaluation": [0],
                            "benchmarks": [1],
                            "track": [2],
                            "AI": [3],
                            "progress": [4],
                        },
                        "authorships": [
                            {"author": {"display_name": "Research Author"}}
                        ],
                    }
                ]
            }

    monkeypatch.setattr(
        "src.source_connectors.requests.get",
        lambda *args, **kwargs: Response(),
    )
    store = LocalStateStore(str(tmp_path / "openalex.db"))
    run_service = ResearchRunService(store)
    run = await run_service.create_run(
        "TEN-1",
        "PRJ-1",
        ResearchRequest(
            title="Latest AI",
            primary_question="What is the latest on AI?",
            scope_description="Recent papers",
            max_sources=2,
        ),
    )
    service = EvidenceService(store, connector=OpenAlexConnector())

    result = await service.discover_and_ingest_plan(
        "TEN-1",
        "PRJ-1",
        run.run_id,
        {"search_queries": ["latest on AI"]},
    )
    found = await service.search_evidence(
        "TEN-1", "PRJ-1", run.run_id, "benchmarks AI"
    )

    assert result["sources"][0].source_type.value == "paper"
    assert result["sources"][0].connector == "openalex"
    assert result["evidence"][0].title == "AI evaluation trends in 2026"
    assert found[0].source_id == result["sources"][0].source_id
