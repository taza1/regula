"""Regression tests for the audited source and evidence hardening backlog."""

from datetime import datetime

import pytest

from src.evidence_extraction import ExtractionError, _download
from src.local_store import LocalStateStore
from src.source_connectors import (
    ArxivConnector,
    CompositeScholarlyConnector,
    FallbackSourceConnector,
    LocalSourceConnector,
    SourceRecord,
    _request_with_retry,
    _user_agent,
)


class FakeConnector:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self.result = result or []
        self.error = error

    async def search(self, query, **kwargs):
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_composite_reports_partial_provider_failure_and_interleaves():
    connector = CompositeScholarlyConnector((
        FakeConnector("first", [SourceRecord(source_id="1", connector="first", title="One", url="https://one.example/1"),
                                SourceRecord(source_id="2", connector="first", title="Two", url="https://one.example/2")]),
        FakeConnector("failed", error=TimeoutError()),
        FakeConnector("third", [SourceRecord(source_id="3", connector="third", title="Three", url="https://three.example/3")]),
    ))
    result = await connector.search("query", limit=3)
    assert [item.source_id for item in result] == ["1", "3", "2"]
    assert result.outcomes == [
        {"provider": "first", "status": "success"},
        {"provider": "failed", "status": "timeout"},
        {"provider": "third", "status": "success"},
    ]


@pytest.mark.asyncio
async def test_composite_distinguishes_empty_results_from_provider_failure():
    result = await CompositeScholarlyConnector((
        FakeConnector("empty"), FakeConnector("failed", error=RuntimeError("offline")),
    )).search("query")
    assert result == []
    assert result.outcomes == [
        {"provider": "empty", "status": "empty"},
        {"provider": "failed", "status": "failed"},
    ]


def test_connector_retries_rate_limit_then_succeeds(monkeypatch):
    calls = []

    class Response:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("unexpected final response")

    def fake_get(*args, **kwargs):
        calls.append(1)
        return Response(429 if len(calls) == 1 else 200)

    monkeypatch.setattr("src.source_connectors.requests.get", fake_get)
    monkeypatch.setattr("src.source_connectors.time.sleep", lambda delay: None)
    response = _request_with_retry("https://api.example/works", params={}, timeout=1,
                                   headers={}, retries=1, backoff_seconds=0)
    assert response.status_code == 200
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_fallback_is_explicitly_labeled():
    connector = FallbackSourceConnector(FakeConnector("remote", error=RuntimeError("offline")),
                                        LocalSourceConnector())
    result = await connector.search("unmatched topic", limit=1)
    assert result[0].metadata["fallback"] is True
    assert result[0].metadata["synthetic"] is True
    assert result.outcomes[0] == {"provider": "remote", "status": "failed"}
    assert result.outcomes[1]["fallback"] is True


def test_arxiv_applies_date_query_sorting_and_rejects_bad_xml(monkeypatch):
    captured = {}

    class Response:
        text = "<not-closed"

        def raise_for_status(self):
            return None

    def fake_get(url, params, timeout, headers):
        captured.update(params)
        return Response()

    monkeypatch.setattr("src.source_connectors.requests.get", fake_get)
    with pytest.raises(ValueError, match="Invalid arXiv XML"):
        ArxivConnector(request_interval_seconds=0).search_sync(
            "latest AI", limit=2,
            date_range_start=datetime(2026, 1, 1), date_range_end=datetime(2026, 9, 1),
        )
    assert "submittedDate:[202601010000 TO 202609012359]" in captured["search_query"]
    assert captured["sortBy"] == "submittedDate"
    assert captured["sortOrder"] == "descending"


def test_arxiv_rejects_oversized_xml(monkeypatch):
    class Response:
        text = "x" * 2_000_001

        def raise_for_status(self):
            return None

    monkeypatch.setattr("src.source_connectors.requests.get", lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match="payload exceeds limit"):
        ArxivConnector(request_interval_seconds=0).search_sync("AI", limit=1)


def test_user_agent_removes_header_line_breaks():
    value = _user_agent("person@example.test\r\nX-Injected: yes")
    assert "\r" not in value and "\n" not in value
    assert "X-Injected: yes" in value


def test_snapshot_insert_is_idempotent_but_conflicts_are_rejected(tmp_path):
    store = LocalStateStore(str(tmp_path / "immutable.db"))
    payload = {"snapshot_id": "SSN-1", "content_hash": "sha256:one", "text": "one",
               "created_at": "first", "retrieved_at": "first"}
    store.put("source_snapshot", "TEN", "PRJ", "SSN-1", payload)
    retry = {**payload, "created_at": "retry", "retrieved_at": "retry"}
    store.put("source_snapshot", "TEN", "PRJ", "SSN-1", retry)
    assert store.get("source_snapshot", "TEN", "PRJ", "SSN-1") == payload
    with pytest.raises(ValueError, match="Immutable snapshot conflict"):
        store.put("source_snapshot", "TEN", "PRJ", "SSN-1", {**retry, "text": "changed"})


def test_download_rejects_private_address_before_connection(monkeypatch):
    monkeypatch.setattr("src.evidence_extraction.socket.getaddrinfo",
                        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(ExtractionError, match="not public"):
        _download("https://papers.example/doc", ["papers.example"], [], 1, 100)


def test_download_enforces_limit_while_streaming(monkeypatch):
    class Response:
        status = 200
        headers = {"Content-Type": "text/html"}

        def read1(self, size, decode_content=False):
            return b"x" * size

        def close(self):
            pass

    class Pool:
        def __init__(self, *args, **kwargs):
            pass

        def urlopen(self, *args, **kwargs):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("src.evidence_extraction.socket.getaddrinfo",
                        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    monkeypatch.setattr("src.evidence_extraction.urllib3.HTTPSConnectionPool", Pool)
    with pytest.raises(ExtractionError, match="maximum size"):
        _download("https://papers.example/doc", ["papers.example"], [], 1, 100)


def test_download_revalidates_redirect_target(monkeypatch):
    class Response:
        status = 302
        headers = {"Location": "http://169.254.169.254/latest/meta-data"}

        def close(self):
            pass

    class Pool:
        def __init__(self, *args, **kwargs):
            pass

        def urlopen(self, *args, **kwargs):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("src.evidence_extraction.socket.getaddrinfo",
                        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    monkeypatch.setattr("src.evidence_extraction.urllib3.HTTPSConnectionPool", Pool)
    with pytest.raises(ExtractionError, match="outside the approved"):
        _download("https://papers.example/doc", ["papers.example"], [], 1, 100)
