"""Safe full-text retrieval, extraction, chunking, and content deduplication."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import requests

from src.source_connectors import SourceRecord


class ExtractionError(RuntimeError):
    """Raised when a source cannot be safely retrieved or extracted."""


@dataclass(frozen=True)
class ExtractedDocument:
    url: str
    media_type: str
    text: str
    content_hash: str


def _host_allowed(url: str, approved_domains: list[str], excluded_domains: list[str]) -> bool:
    hostname = (urlparse(url).hostname or "").casefold()
    if not hostname or urlparse(url).scheme not in {"http", "https"}:
        return False
    matches = lambda domain: hostname == domain.casefold().removeprefix("*.") or hostname.endswith(
        "." + domain.casefold().removeprefix("*.")
    )
    return not any(matches(domain) for domain in excluded_domains) and (
        not approved_domains or any(matches(domain) for domain in approved_domains)
    )


def fetch_document(
    source: SourceRecord,
    *,
    approved_domains: Optional[list[str]] = None,
    excluded_domains: Optional[list[str]] = None,
    timeout_seconds: float = 20.0,
    max_bytes: int = 10_000_000,
    session=requests,
) -> ExtractedDocument:
    """Fetch an approved HTML/PDF URL and return normalized text."""

    approved_domains = approved_domains or []
    excluded_domains = excluded_domains or []
    url = str(source.metadata.get("pdf_url") or source.url)
    if not _host_allowed(url, approved_domains, excluded_domains):
        raise ExtractionError("document URL is outside the approved source-domain policy")
    response = session.get(
        url,
        timeout=timeout_seconds,
        headers={"User-Agent": "research-system-local/0.1"},
    )
    response.raise_for_status()
    content = response.content
    if len(content) > max_bytes:
        raise ExtractionError("document exceeds the configured maximum size")
    media_type = response.headers.get("Content-Type", "").split(";", 1)[0].casefold()
    is_pdf = media_type == "application/pdf" or url.casefold().split("?", 1)[0].endswith(".pdf")
    if is_pdf:
        text = _extract_pdf(content)
        media_type = "application/pdf"
    elif media_type in {"text/html", "application/xhtml+xml"} or "<html" in content[:1000].decode("utf-8", "ignore").casefold():
        text = _extract_html(content)
        media_type = "text/html"
    else:
        raise ExtractionError(f"unsupported document media type: {media_type or 'unknown'}")
    normalized = _normalize_text(text)
    if not normalized:
        raise ExtractionError("document contained no extractable text")
    return ExtractedDocument(url=url, media_type=media_type, text=normalized,
                             content_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest())


def chunk_text(text: str, *, max_chars: int = 2000, overlap_chars: int = 200) -> list[str]:
    """Split normalized text into bounded, paragraph-aware chunks."""

    if max_chars <= 0 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("chunk size must be positive and overlap must be smaller than chunk size")
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", _normalize_text(text)) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), max_chars - overlap_chars):
                chunks.append(paragraph[start:start + max_chars].strip())
            continue
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = f"{current[-overlap_chars:]}\n\n{paragraph}".strip() if overlap_chars else paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    unique: list[str] = []
    hashes: set[str] = set()
    for chunk in chunks:
        digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
        if digest not in hashes:
            hashes.add(digest)
            unique.append(chunk)
    return unique


def _extract_html(content: bytes) -> str:
    try:
        import trafilatura
        extracted = trafilatura.extract(content.decode("utf-8", "replace"), include_comments=False)
        if extracted:
            return extracted
    except ImportError:
        pass
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return soup.get_text("\n")


def _extract_pdf(content: bytes) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise ExtractionError("PDF extraction requires pymupdf") from exc
    with fitz.open(stream=io.BytesIO(content), filetype="pdf") as document:
        return "\n\n".join(page.get_text("text") for page in document)


def _normalize_text(value: str) -> str:
    return "\n\n".join(
        " ".join(line.split()) for line in re.split(r"\n\s*\n", value or "") if line.strip()
    ).strip()
