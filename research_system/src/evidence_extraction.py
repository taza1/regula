"""Safe full-text retrieval, extraction, chunking, and content deduplication."""

from __future__ import annotations

import hashlib
import io
import re
import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, urljoin

import urllib3

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


def _download(url, approved_domains, excluded_domains, timeout_seconds, max_bytes, max_redirects=5):
    """Pin each connection to a validated public IP, retaining TLS hostname checks.

    Proxy environment variables are intentionally not used for source downloads.
    Only identity encoding is accepted to bound memory before decompression.
    """
    deadline = time.monotonic() + timeout_seconds
    for hop in range(max_redirects + 1):
        if not approved_domains or not _host_allowed(url, approved_domains, excluded_domains):
            raise ExtractionError("document URL is outside the approved source-domain policy")
        parsed = urlparse(url)
        if parsed.username or parsed.password or any(ord(c) < 32 for c in url):
            raise ExtractionError("invalid document URL")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in {80, 443}:
            raise ExtractionError("document port is not permitted")
        addresses = {entry[4][0] for entry in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ExtractionError("document address is not public")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExtractionError("document download deadline exceeded")
        address = sorted(addresses)[0]
        pool_type = urllib3.HTTPSConnectionPool if parsed.scheme == "https" else urllib3.HTTPConnectionPool
        tls_options = {"server_hostname": parsed.hostname, "assert_hostname": parsed.hostname,
                       "cert_reqs": "CERT_REQUIRED"} if parsed.scheme == "https" else {}
        pool = pool_type(address, port=port, **tls_options)
        response = None
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            response = pool.urlopen("GET", path, headers={"Host": parsed.netloc,
                "User-Agent": "research-system-local/0.1", "Accept-Encoding": "identity"},
                redirect=False, retries=False, preload_content=False,
                timeout=urllib3.Timeout(total=remaining, connect=min(remaining, 5), read=min(remaining, 5)))
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if hop == max_redirects or not location:
                    raise ExtractionError("document redirect limit or invalid redirect")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ExtractionError("document retrieval failed")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ExtractionError("compressed document transfer is not permitted")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > max_bytes):
                raise ExtractionError("document exceeds the configured maximum size")
            content = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise ExtractionError("document download deadline exceeded")
                chunk = response.read1(min(65536, max_bytes + 1 - len(content)), decode_content=False)
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise ExtractionError("document exceeds the configured maximum size")
            return bytes(content), dict(response.headers), url
        except urllib3.exceptions.HTTPError as exc:
            raise ExtractionError("document transport failed") from exc
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise ExtractionError("document redirect limit exceeded")


def fetch_document(
    source: SourceRecord,
    *,
    approved_domains: Optional[list[str]] = None,
    excluded_domains: Optional[list[str]] = None,
    timeout_seconds: float = 20.0,
    max_bytes: int = 10_000_000,
) -> ExtractedDocument:
    """Fetch an approved HTML/PDF URL and return normalized text."""

    approved_domains = approved_domains or []
    excluded_domains = excluded_domains or []
    url = str(source.metadata.get("pdf_url") or source.url)
    if not _host_allowed(url, approved_domains, excluded_domains):
        raise ExtractionError("document URL is outside the approved source-domain policy")
    if timeout_seconds <= 0 or max_bytes <= 0:
        raise ValueError("download limits must be positive")
    content, headers, url = _download(url, approved_domains, excluded_domains, timeout_seconds, max_bytes)
    media_type = headers.get("Content-Type", "").split(";", 1)[0].casefold()
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
            overlap = min(overlap_chars, max(0, max_chars - len(paragraph) - 2))
            current = f"{current[-overlap:]}\n\n{paragraph}".strip() if overlap else paragraph
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
