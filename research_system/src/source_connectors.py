"""Offline source discovery contracts and the deterministic local connector.

Connectors return metadata and a bounded passage instead of fetching content.
That keeps local development deterministic and gives remote adapters (OpenAlex,
Crossref, arXiv, or another approved provider) a small interface to implement
without changing the evidence service.
"""

from __future__ import annotations

import hashlib
import re
import random
import threading
import time
from defusedxml import ElementTree as ET
from itertools import zip_longest
from datetime import datetime, timedelta
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

import requests
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models import (
    EligibilityStatus,
    PeerReviewStatus,
    SourceType,
    SourceUseDecision,
)

_THROTTLE_LOCK = threading.Lock()
_LAST_REQUEST_BY_DOMAIN: dict[str, float] = {}


class SourceResults(list):
    """List-compatible results with per-request provider outcomes (no shared state)."""

    def __init__(self, values=(), outcomes=()):
        super().__init__(values)
        self.outcomes = list(outcomes)


async def search_with_outcome(connector, query, **kwargs):
    try:
        results = await connector.search(query, **kwargs)
        if isinstance(results, SourceResults):
            return results
        return SourceResults(results, [{"provider": connector.name,
                                       "status": "success" if results else "empty"}])
    except Exception as exc:
        status = "timeout" if isinstance(exc, (requests.Timeout, TimeoutError)) else "failed"
        if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code == 429:
            status = "rate_limited"
        return SourceResults(outcomes=[{"provider": connector.name, "status": status}])


def _request_with_retry(
    url: str,
    *,
    params: dict[str, Any],
    timeout: float,
    headers: dict[str, str],
    min_interval_seconds: float = 0.0,
    retries: int = 3,
    backoff_seconds: float = 0.5,
):
    """Perform a polite, bounded request with retry/backoff for transient failures."""

    domain = re.sub(r"^https?://", "", url).split("/", 1)[0].casefold()
    for attempt in range(retries + 1):
        with _THROTTLE_LOCK:
            elapsed = time.monotonic() - _LAST_REQUEST_BY_DOMAIN.get(domain, 0.0)
            delay = max(0.0, min_interval_seconds - elapsed)
            if delay:
                time.sleep(delay)
            _LAST_REQUEST_BY_DOMAIN[domain] = time.monotonic()
        try:
            response = requests.get(url, params=params, timeout=timeout, headers=headers)
            status = getattr(response, "status_code", 200)
            if status == 429 or status >= 500:
                if attempt < retries:
                    time.sleep(backoff_seconds * (2 ** attempt) + random.uniform(0, 0.1))
                    continue
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt >= retries:
                raise
            time.sleep(backoff_seconds * (2 ** attempt) + random.uniform(0, 0.1))
    raise RuntimeError("request retry loop exited unexpectedly")


class SourceRecord(BaseModel):
    """A discovered source and the local content available for ingestion.

    The scope fields are populated by :class:`EvidenceService`.  Connector
    implementations should normally leave them empty because discovery is
    reusable; the service adds the tenant/project/run boundary before storing
    the record.
    """

    model_config = ConfigDict(from_attributes=True)

    source_id: str
    connector: str
    title: str
    url: str
    source_type: SourceType = SourceType.REPORT
    abstract: str = ""
    passage: str = ""
    authors: list[str] = Field(default_factory=list)
    doi: Optional[str] = None
    published_at: Optional[datetime] = None
    peer_review_status: PeerReviewStatus = PeerReviewStatus.UNKNOWN
    license: Optional[str] = None
    source_use_decision: SourceUseDecision = SourceUseDecision.ALLOWED
    eligibility_status: EligibilityStatus = EligibilityStatus.ELIGIBLE
    policy_version: str = "LOCAL-1"
    metadata: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = ""
    project_id: str = ""
    run_id: str = ""

    @model_validator(mode="after")
    def populate_content(self) -> "SourceRecord":
        """Accept either connector-style abstracts or ingestion-style passages."""

        if not self.passage:
            self.passage = self.abstract
        if not self.abstract:
            self.abstract = self.passage
        return self


@runtime_checkable
class SourceConnector(Protocol):
    """Interface implemented by local and future remote source adapters."""

    name: str

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        date_range_start: Optional[datetime] = None,
        date_range_end: Optional[datetime] = None,
    ) -> list[SourceRecord]:
        """Return deterministic, bounded source metadata for ``query``."""


class ConnectorUnavailableError(RuntimeError):
    """Raised when a remote connector is selected but not configured."""


class RemoteSourceConnector:
    """Safe placeholder for a future network-backed connector.

    It intentionally performs no network I/O.  A production adapter can
    implement ``search`` using the same interface once its policy and
    credentials are configured.
    """

    name = "remote-unconfigured"

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        date_range_start: Optional[datetime] = None,
        date_range_end: Optional[datetime] = None,
    ) -> list[SourceRecord]:
        raise ConnectorUnavailableError(
            f"{self.name} is not enabled in the local/offline runtime"
        )


class OpenAlexConnector:
    """OpenAlex Works API adapter for the first real scholarly-search slice."""

    name = "openalex"

    def __init__(
        self,
        *,
        base_url: str = "https://api.openalex.org",
        mailto: str = "",
        timeout_seconds: float = 20.0,
        latest_query_days: int = 180,
        request_interval_seconds: float = 0.1,
    ):
        self.base_url = base_url.rstrip("/")
        self.mailto = " ".join(mailto.split())
        self.timeout_seconds = timeout_seconds
        self.latest_query_days = latest_query_days
        self.request_interval_seconds = request_interval_seconds

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        date_range_start: Optional[datetime] = None,
        date_range_end: Optional[datetime] = None,
    ) -> list[SourceRecord]:
        """Search OpenAlex works and return paper-like source records."""

        import asyncio

        return await asyncio.to_thread(
            self.search_sync,
            query,
            limit=limit,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
        )

    def search_sync(
        self,
        query: str,
        *,
        limit: int = 20,
        date_range_start: Optional[datetime] = None,
        date_range_end: Optional[datetime] = None,
    ) -> list[SourceRecord]:
        normalized = " ".join(query.split())
        if not normalized or int(limit) <= 0:
            return []
        inferred_latest_window = (
            date_range_start is None and _looks_like_latest_query(normalized)
        )
        if inferred_latest_window:
            date_range_start = datetime.utcnow() - timedelta(days=self.latest_query_days)
            if date_range_end is None:
                date_range_end = datetime.utcnow()
        bounded_limit = max(1, min(int(limit), 100))
        filters: list[str] = []
        if date_range_start is not None:
            filters.append(
                f"from_publication_date:{date_range_start.date().isoformat()}"
            )
        if date_range_end is not None:
            filters.append(
                f"to_publication_date:{date_range_end.date().isoformat()}"
            )
        search_text = _openalex_search_text(normalized)
        params: dict[str, Any] = {
            "search": search_text,
            "per-page": bounded_limit,
            "sort": "publication_date:desc"
            if _looks_like_latest_query(normalized) or date_range_start
            else "relevance_score:desc",
        }
        if filters:
            params["filter"] = ",".join(filters)
        if self.mailto:
            params["mailto"] = self.mailto

        response = _request_with_retry(
            f"{self.base_url}/works",
            params=params,
            timeout=self.timeout_seconds,
            headers={"User-Agent": _user_agent(self.mailto)},
            min_interval_seconds=self.request_interval_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return [
            record
            for item in data.get("results", [])
            if (record := self._record_from_work(item)) is not None
        ][:bounded_limit]

    def _record_from_work(self, item: dict[str, Any]) -> Optional[SourceRecord]:
        title = (item.get("display_name") or item.get("title") or "").strip()
        openalex_id = str(item.get("id") or "").strip()
        if not title or not openalex_id:
            return None
        abstract = _abstract_from_inverted_index(item.get("abstract_inverted_index"))
        if not abstract:
            abstract = (
                "OpenAlex returned metadata for this work, but no abstract text "
                "was available in the API response."
            )
        doi = _clean_doi(item.get("doi"))
        publication_date = _parse_date(item.get("publication_date"))
        work_type = str(item.get("type") or "").casefold()
        source_type = SourceType.PREPRINT if "preprint" in work_type else SourceType.PAPER
        peer_review_status = (
            PeerReviewStatus.PREPRINT
            if source_type == SourceType.PREPRINT
            else PeerReviewStatus.UNKNOWN
        )
        host_venue = item.get("host_venue") or {}
        primary_location = item.get("primary_location") or {}
        best_url = (
            item.get("doi")
            or item.get("landing_page_url")
            or primary_location.get("landing_page_url")
            or host_venue.get("url")
            or openalex_id
        )
        source_id = "OPENALEX-" + _stable_id(openalex_id)
        authors = [
            str(author.get("author", {}).get("display_name")).strip()
            for author in item.get("authorships", [])
            if author.get("author", {}).get("display_name")
        ]
        return SourceRecord(
            source_id=source_id,
            connector=self.name,
            title=title,
            url=str(best_url),
            source_type=source_type,
            abstract=abstract,
            authors=authors,
            doi=doi,
            published_at=publication_date,
            peer_review_status=peer_review_status,
            license=_openalex_license(item),
            metadata={
                "openalex_id": openalex_id,
                "publication_year": item.get("publication_year"),
                "cited_by_count": item.get("cited_by_count"),
                "work_type": item.get("type"),
                "source_display_name": (
                    (item.get("primary_location") or {})
                    .get("source", {})
                    .get("display_name")
                )
                or host_venue.get("display_name"),
                "is_retracted": item.get("is_retracted"),
                "open_access": item.get("open_access"),
            },
            policy_version="OPENALEX-1",
        )


class CrossrefConnector:
    """Crossref Works API adapter."""

    name = "crossref"

    def __init__(self, *, base_url="https://api.crossref.org", mailto="", timeout_seconds=20.0,
                 latest_query_days=180, request_interval_seconds=0.1):
        self.base_url = base_url.rstrip("/")
        self.mailto = " ".join(mailto.split())
        self.timeout_seconds = timeout_seconds
        self.latest_query_days = latest_query_days
        self.request_interval_seconds = request_interval_seconds

    async def search(self, query, *, limit=20, date_range_start=None, date_range_end=None):
        import asyncio
        return await asyncio.to_thread(self.search_sync, query, limit=limit,
                                       date_range_start=date_range_start, date_range_end=date_range_end)

    def search_sync(self, query, *, limit=20, date_range_start=None, date_range_end=None):
        normalized = " ".join(query.split())
        if not normalized or int(limit) <= 0:
            return []
        if date_range_start is None and _looks_like_latest_query(normalized):
            date_range_start = datetime.utcnow() - timedelta(days=self.latest_query_days)
            date_range_end = date_range_end or datetime.utcnow()
        bounded_limit = min(max(int(limit), 1), 1000)
        params = {"query": normalized, "rows": bounded_limit}
        if self.mailto:
            params["mailto"] = self.mailto
        if date_range_start:
            params["filter"] = f"from-pub-date:{date_range_start.date().isoformat()}"
        if date_range_end:
            end_filter = f"until-pub-date:{date_range_end.date().isoformat()}"
            params["filter"] = f"{params['filter']},{end_filter}" if "filter" in params else end_filter
        response = _request_with_retry(
            f"{self.base_url}/works", params=params, timeout=self.timeout_seconds,
            headers={"User-Agent": _user_agent(self.mailto)},
            min_interval_seconds=self.request_interval_seconds,
        )
        response.raise_for_status()
        items = response.json().get("message", {}).get("items", [])
        return [record for item in items if (record := self._record_from_work(item)) is not None][:bounded_limit]

    def _record_from_work(self, item):
        doi = _clean_doi(item.get("DOI"))
        resource = item.get("resource") or {}
        url = item.get("URL") or (resource.get("primary") or {}).get("URL")
        if not url and doi:
            url = f"https://doi.org/{doi}"
        title = next((str(value).strip() for value in item.get("title", []) if str(value).strip()), "")
        if not title or not (doi or url):
            return None
        abstract = _clean_markup(item.get("abstract", ""))
        if not abstract:
            abstract = "Crossref returned metadata for this work, but no abstract text was available."
        authors = []
        for author in item.get("author", []):
            name = " ".join(str(author.get(key, "")).strip() for key in ("given", "family")).strip()
            authors.append(name or str(author.get("name", "")).strip())
        authors = [author for author in authors if author]
        work_type = str(item.get("type", "")).casefold()
        is_preprint = work_type == "posted-content" or "preprint" in work_type
        return SourceRecord(
            source_id="CROSSREF-" + _stable_id(doi or url),
            connector=self.name, title=title, url=str(url),
            source_type=SourceType.PREPRINT if is_preprint else SourceType.PAPER,
            abstract=abstract, authors=authors, doi=doi,
            published_at=_crossref_date(item),
            peer_review_status=(PeerReviewStatus.PREPRINT if is_preprint else
                                PeerReviewStatus.PEER_REVIEWED if work_type in
                                {"journal-article", "book-chapter", "proceedings-article"} else
                                PeerReviewStatus.UNKNOWN),
            license=_crossref_license(item),
            metadata={"crossref_doi": doi, "doi": doi, "container_title": (item.get("container-title") or [None])[0],
                      "publisher": item.get("publisher"), "type": item.get("type"),
                      "is_referenced_by_count": item.get("is-referenced-by-count")},
            policy_version="CROSSREF-1",
        )


class ArxivConnector:
    """arXiv Atom API adapter."""

    name = "arxiv"

    def __init__(self, *, base_url="https://export.arxiv.org/api/query", timeout_seconds=20.0,
                 request_interval_seconds=3.0, latest_query_days=180, max_pages=5):
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.request_interval_seconds = request_interval_seconds
        self.latest_query_days = latest_query_days
        self.max_pages = max(1, min(int(max_pages), 10))

    async def search(self, query, *, limit=20, date_range_start=None, date_range_end=None):
        import asyncio
        return await asyncio.to_thread(self.search_sync, query, limit=limit,
                                       date_range_start=date_range_start, date_range_end=date_range_end)

    def search_sync(self, query, *, limit=20, date_range_start=None, date_range_end=None):
        normalized = " ".join(query.split())
        if not normalized or int(limit) <= 0:
            return []
        bounded_limit = min(max(int(limit), 1), 100)
        recent = _looks_like_latest_query(normalized)
        if date_range_start is None and recent:
            date_range_start = datetime.utcnow() - timedelta(days=self.latest_query_days)
            date_range_end = date_range_end or datetime.utcnow()
        query_text = f"all:({normalized})"
        if date_range_start or date_range_end:
            start = date_range_start.strftime("%Y%m%d0000") if date_range_start else "199101010000"
            end = date_range_end.strftime("%Y%m%d2359") if date_range_end else datetime.utcnow().strftime("%Y%m%d2359")
            query_text += f" AND submittedDate:[{start} TO {end}]"
        records = []
        seen = set()
        for page in range(self.max_pages):
            response = _request_with_retry(
                self.base_url,
                params={"search_query": query_text, "start": page * bounded_limit,
                        "max_results": bounded_limit, "sortBy": "submittedDate" if recent or date_range_start or date_range_end else "relevance",
                        "sortOrder": "descending"},
                timeout=self.timeout_seconds, headers={"User-Agent": _user_agent("")},
                min_interval_seconds=self.request_interval_seconds,
            )
            payload = response.text if hasattr(response, "text") else response.content
            if len(payload.encode("utf-8") if isinstance(payload, str) else payload) > 2_000_000:
                raise ValueError("arXiv XML payload exceeds limit")
            try:
                root = ET.fromstring(payload)
            except Exception as exc:
                raise ValueError("Invalid arXiv XML response") from exc
            entries = root.findall("{http://www.w3.org/2005/Atom}entry")
            for entry in entries:
                record = self._record_from_entry(entry)
                if record and record.source_id not in seen and _in_date_range(record.published_at, date_range_start, date_range_end):
                    seen.add(record.source_id)
                    records.append(record)
            if len(records) >= bounded_limit or len(entries) < bounded_limit:
                break
        return records[:bounded_limit]

    def _record_from_entry(self, entry):
        atom = "{http://www.w3.org/2005/Atom}"
        arxiv_ns = "{http://arxiv.org/schemas/atom}"
        raw_id = (entry.findtext(atom + "id") or "").strip()
        arxiv_id = _arxiv_id(raw_id)
        title = " ".join((entry.findtext(atom + "title") or "").split())
        if not arxiv_id or not title:
            return None
        links = entry.findall(atom + "link")
        abs_url = next((link.get("href") for link in links if link.get("rel") == "alternate"), None)
        pdf_url = next((link.get("href") for link in links if link.get("title") == "pdf"), None)
        license_url = next((link.get("href") for link in links if "license" in (link.get("rel") or "").casefold()), None)
        doi = _clean_doi(entry.findtext(arxiv_ns + "doi"))
        return SourceRecord(
            source_id="ARXIV-" + _stable_id(arxiv_id), connector=self.name, title=title,
            url=abs_url or f"http://arxiv.org/abs/{arxiv_id}", source_type=SourceType.PREPRINT,
            abstract=" ".join((entry.findtext(atom + "summary") or "").split()),
            authors=[name for name in (author.findtext(atom + "name") for author in entry.findall(atom + "author"))
                     if name],
            doi=doi, published_at=_parse_date(entry.findtext(atom + "published")),
            peer_review_status=PeerReviewStatus.PREPRINT, license=license_url,
            metadata={"arxiv_id": arxiv_id,
                      "primary_category": (entry.find(arxiv_ns + "primary_category").get("term")
                                           if entry.find(arxiv_ns + "primary_category") is not None else None),
                      "categories": [node.get("term") for node in entry.findall(atom + "category") if node.get("term")],
                      "journal_ref": entry.findtext(arxiv_ns + "journal_ref"),
                      "comment": entry.findtext(arxiv_ns + "comment"), "pdf_url": pdf_url},
            policy_version="ARXIV-1",
        )


class CompositeScholarlyConnector:
    """Aggregate scholarly providers while collapsing cross-provider duplicates."""

    name = "scholarly"

    def __init__(self, connectors):
        self.connectors = tuple(connectors)

    async def search(self, query, *, limit=20, date_range_start=None, date_range_end=None):
        import asyncio
        batches = await asyncio.gather(*(search_with_outcome(
            connector, query, limit=limit, date_range_start=date_range_start,
            date_range_end=date_range_end) for connector in self.connectors))
        interleaved = [item for row in zip_longest(*batches) for item in row if item is not None]
        return SourceResults(deduplicate_sources(interleaved)[:max(0, int(limit))],
                             [outcome for batch in batches for outcome in batch.outcomes])


def deduplicate_sources(sources):
    """Collapse records sharing DOI, arXiv, OpenAlex, or canonical identifiers."""
    seen = set()
    unique = []
    for source in sources:
        identifiers = _source_identifiers(source)
        if identifiers & seen:
            continue
        seen.update(identifiers)
        unique.append(source)
    return unique


def _clean_markup(value):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(str(value or ""), "html.parser")
    for node in soup(["script", "style"]):
        node.decompose()
    return " ".join(soup.get_text(" ").split())


def _crossref_date(item):
    for key in ("published", "published-online", "published-print", "issued"):
        parts = (item.get(key) or {}).get("date-parts", [])
        if parts and parts[0]:
            values = parts[0]
            try:
                return datetime(int(values[0]), int(values[1]) if len(values) > 1 else 1,
                                int(values[2]) if len(values) > 2 else 1)
            except (TypeError, ValueError):
                continue
    return None


def _crossref_license(item):
    for license_item in item.get("license", []) or []:
        url = license_item.get("URL") if isinstance(license_item, dict) else None
        if url:
            return url
    return None


def _arxiv_id(value):
    abs_match = re.search(r"/abs/([^/?#]+)", value.casefold())
    if abs_match:
        return re.sub(r"v\d+$", "", abs_match.group(1))
    match = re.search(r"(?:arxiv[.:/])?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+[./]\d{4,5}(?:v\d+)?)", value.casefold())
    result = match.group(1) if match else value.rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", result.removesuffix("."))


def _source_identifiers(source):
    identifiers = set()
    doi = _clean_doi(source.doi)
    if doi:
        identifiers.add("doi:" + doi.casefold())
        if "10.48550/arxiv." in doi.casefold():
            identifiers.add("arxiv:" + _arxiv_id(doi))
    metadata = source.metadata or {}
    for key in ("doi", "crossref_doi"):
        value = _clean_doi(metadata.get(key))
        if value:
            identifiers.add("doi:" + value.casefold())
    for key in ("arxiv_id", "openalex_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            identifiers.add(key + ":" + (_arxiv_id(value) if key == "arxiv_id" else value.rstrip("/").casefold()))
    for value in (source.source_id, source.url):
        if isinstance(value, str) and value:
            if "arxiv" in value.casefold():
                identifiers.add("arxiv:" + _arxiv_id(value))
            if "openalex.org/" in value.casefold():
                identifiers.add("openalex:" + value.rstrip("/").rsplit("/", 1)[-1].casefold())
    identifiers.add("canonical:" + _stable_id(source.title.casefold()))
    return identifiers


def _in_date_range(value, start, end):
    if value is None:
        return False
    value_date = value.date()
    return (start is None or value_date >= start.date()) and (end is None or value_date <= end.date())


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{2,}", value.casefold())
        if token not in {"and", "for", "the", "with", "from", "what", "does"}
    }


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16].upper()


class LocalSourceConnector:
    """Deterministic, offline-only source connector.

    The small catalogue provides useful repeatable fixtures for common
    research terms.  Unknown queries still produce a clearly labelled local
    record derived from the query, so the complete planner -> discovery ->
    ingestion path can be exercised without a network or credentials.
    """

    name = "local"

    def __init__(self, catalogue: Optional[Sequence[SourceRecord]] = None):
        self._catalogue = tuple(
            self._default_catalogue() if catalogue is None else catalogue
        )

    @staticmethod
    def _default_catalogue() -> tuple[SourceRecord, ...]:
        return (
            SourceRecord(
                source_id="LOCAL-CLIMATE-001",
                connector="local",
                title="Offline evidence note: climate intervention outcomes",
                url="local://sources/climate-intervention-outcomes",
                abstract=(
                    "A deterministic local fixture describing how measured "
                    "intervention outcomes can vary by population, follow-up "
                    "period, and study design."
                ),
                authors=["Local Evidence Group"],
                published_at=datetime(2024, 1, 1),
                peer_review_status=PeerReviewStatus.PEER_REVIEWED,
                metadata={"keywords": ["climate", "intervention", "outcomes"]},
            ),
            SourceRecord(
                source_id="LOCAL-METHODS-001",
                connector="local",
                title="Offline evidence note: research methods and limitations",
                url="local://sources/research-methods-limitations",
                abstract=(
                    "A deterministic local fixture noting that observational "
                    "associations do not by themselves establish causation and "
                    "that independent origins should be checked."
                ),
                authors=["Local Methods Group"],
                published_at=datetime(2024, 2, 1),
                peer_review_status=PeerReviewStatus.PEER_REVIEWED,
                metadata={"keywords": ["methods", "limitations", "evidence"]},
            ),
            SourceRecord(
                source_id="LOCAL-CONTRARY-001",
                connector="local",
                title="Offline evidence note: contradictory findings",
                url="local://sources/contradictory-findings",
                abstract=(
                    "A deterministic local fixture for negative evidence: "
                    "results may be mixed, imprecise, or sensitive to the "
                    "assumptions and populations used in a study."
                ),
                authors=["Local Review Group"],
                published_at=datetime(2024, 3, 1),
                peer_review_status=PeerReviewStatus.UNKNOWN,
                metadata={
                    "keywords": [
                        "contradictory",
                        "negative",
                        "limitations",
                        "mixed",
                    ]
                },
            ),
        )

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        date_range_start: Optional[datetime] = None,
        date_range_end: Optional[datetime] = None,
    ) -> list[SourceRecord]:
        """Search the local catalogue without performing I/O."""

        return self.search_sync(query, limit=limit)

    def search_sync(self, query: str, *, limit: int = 20) -> list[SourceRecord]:
        """Synchronous convenience wrapper for scripts and unit tests."""

        normalized = " ".join(query.split())
        if not normalized or int(limit) <= 0:
            return []
        bounded_limit = min(int(limit), 100)
        query_tokens = _tokens(normalized)
        ranked: list[tuple[int, str, SourceRecord]] = []
        for source in self._catalogue:
            keywords = source.metadata.get("keywords", [])
            searchable = _tokens(
                " ".join([source.title, source.abstract, *map(str, keywords)])
            )
            score = len(query_tokens & searchable)
            if score:
                ranked.append((score, source.source_id, source))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        matches = [source for _, _, source in ranked[:bounded_limit]]
        if matches:
            return matches

        # Query-derived fallback makes arbitrary planner output ingestible,
        # while the local:// URL makes the offline provenance explicit.
        digest = _stable_id(normalized)
        safe_query = normalized[:180]
        return [
            SourceRecord(
                source_id=f"LOCAL-QUERY-{digest}",
                connector=self.name,
                title=f"Offline evidence note for: {safe_query}",
                url=f"local://queries/{digest.lower()}",
                abstract=(
                    f"Deterministic local evidence fixture for the query "
                    f"“{safe_query}”. This note is available for pipeline "
                    "testing and does not represent a network retrieval."
                ),
                authors=["Local Evidence Fixture"],
                published_at=datetime(2024, 4, 1),
                peer_review_status=PeerReviewStatus.UNKNOWN,
                metadata={"query": normalized, "synthetic": True},
            )
        ][:bounded_limit]


class FallbackSourceConnector:
    """Try a primary connector, then fall back to deterministic local sources."""

    name = "fallback"

    def __init__(
        self,
        primary: SourceConnector,
        fallback: Optional[SourceConnector] = None,
    ):
        self.primary = primary
        self.fallback = fallback or LocalSourceConnector()

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        date_range_start: Optional[datetime] = None,
        date_range_end: Optional[datetime] = None,
    ) -> list[SourceRecord]:
        options = dict(limit=limit, date_range_start=date_range_start, date_range_end=date_range_end)
        results = await search_with_outcome(self.primary, query, **options)
        if results:
            return results
        fallback = await search_with_outcome(self.fallback, query, **options)
        labeled = [item.model_copy(update={"metadata": {**item.metadata, "fallback": True,
                                                       "synthetic": self.fallback.name == "local"}})
                   for item in fallback]
        return SourceResults(labeled, results.outcomes + [dict(item, fallback=True) for item in fallback.outcomes])


def _abstract_from_inverted_index(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    positioned: list[tuple[int, str]] = []
    for token, positions in value.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                positioned.append((position, token))
    positioned.sort(key=lambda item: item[0])
    return " ".join(token for _, token in positioned).strip()


def _parse_date(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _clean_doi(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    doi = value.strip()
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    return doi.removeprefix("doi:").rstrip(".,;")


def _openalex_license(item: dict[str, Any]) -> Optional[str]:
    open_access = item.get("open_access")
    if isinstance(open_access, dict):
        license_name = open_access.get("license")
        if isinstance(license_name, str) and license_name.strip():
            return license_name.strip()
    return None


def _looks_like_latest_query(query: str) -> bool:
    tokens = _tokens(query)
    return bool(tokens & {"latest", "recent", "current", "new", "emerging"})


def _openalex_search_text(query: str) -> str:
    """Keep planner-generated wording inside OpenAlex's search syntax limits."""

    if ":" in query:
        prefix, suffix = query.rsplit(":", 1)
        if suffix.strip() and any(
            marker in prefix.casefold()
            for marker in {"relevant to", "about", "regarding"}
        ):
            query = suffix
    query = re.sub(r"[\"“”]", " ", query)
    query = re.sub(r"[:;!?]+", " ", query)
    return " ".join(query.split())


def _user_agent(mailto: str) -> str:
    mailto = " ".join(mailto.split())
    if mailto:
        return f"research-system-local/0.1 (mailto:{mailto})"
    return "research-system-local/0.1"
