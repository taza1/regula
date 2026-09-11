"""Offline source discovery contracts and the deterministic local connector.

Connectors return metadata and a bounded passage instead of fetching content.
That keeps local development deterministic and gives remote adapters (OpenAlex,
Crossref, arXiv, or another approved provider) a small interface to implement
without changing the evidence service.
"""

from __future__ import annotations

import hashlib
import re
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
    ):
        self.base_url = base_url.rstrip("/")
        self.mailto = mailto.strip()
        self.timeout_seconds = timeout_seconds
        self.latest_query_days = latest_query_days

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

        response = requests.get(
            f"{self.base_url}/works",
            params=params,
            timeout=self.timeout_seconds,
            headers={"User-Agent": _user_agent(self.mailto)},
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


class CrossrefConnector(RemoteSourceConnector):
    """Future Crossref adapter contract."""

    name = "crossref"


class ArxivConnector(RemoteSourceConnector):
    """Future arXiv adapter contract."""

    name = "arxiv"


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
        try:
            results = await self.primary.search(
                query,
                limit=limit,
                date_range_start=date_range_start,
                date_range_end=date_range_end,
            )
        except Exception:
            return await self.fallback.search(
                query,
                limit=limit,
                date_range_start=date_range_start,
                date_range_end=date_range_end,
            )
        return results or await self.fallback.search(
            query,
            limit=limit,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
        )


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
    return doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")


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
    if mailto:
        return f"research-system-local/0.1 (mailto:{mailto})"
    return "research-system-local/0.1"
