"""Policy-checked, request-budgeted, and size-limited source retrieval."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.config import Settings
from app.services.failures import SourceUnavailableError, UnsupportedSourceError
from app.services.registry import match_source_policy

MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3
HTML_TYPES = {"text/html", "application/xhtml+xml"}
PDF_TYPES = {"application/pdf", "application/x-pdf"}


@dataclass
class SourceRequestBudget:
    limit: int
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.limit:
            raise SourceUnavailableError("The source request budget was exhausted")
        self.used += 1


@dataclass(frozen=True)
class RetrievedSource:
    requested_url: str
    resolved_url: str
    content: bytes
    content_type: str
    sha256: str
    retrieved_at: datetime
    source_policy: dict[str, Any]


def _require_public_host(url: str) -> None:
    hostname = urlparse(url).hostname
    if not hostname:
        raise UnsupportedSourceError("Source URL has no hostname")
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise SourceUnavailableError("Source hostname did not resolve") from None
    if not addresses:
        raise SourceUnavailableError("Source hostname did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise UnsupportedSourceError("Source hostname resolved to a non-public address")


def _normalized_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _validate_content_type(content_type: str, url: str, content: bytes) -> str:
    normalized = _normalized_content_type(content_type)
    suffix = urlparse(url).path.lower()
    if normalized in PDF_TYPES or suffix.endswith(".pdf"):
        if not content.lstrip().startswith(b"%PDF-"):
            raise UnsupportedSourceError("Source claimed to be a PDF but has no PDF signature")
        return "application/pdf"
    if normalized in HTML_TYPES or suffix.endswith((".html", ".htm", ".aspx")):
        prefix = content[:1024].lower()
        if b"<html" not in prefix and b"<!doctype html" not in prefix:
            raise UnsupportedSourceError(
                "Source claimed to be HTML but has no HTML document marker"
            )
        return "text/html"
    raise UnsupportedSourceError(f"Unsupported source content type: {normalized or 'missing'}")


def retrieve_source(
    settings: Settings,
    programme: dict[str, Any],
    requested_url: str,
    budget: SourceRequestBudget | None = None,
) -> RetrievedSource:
    current_url = requested_url
    redirect_count = 0
    request_budget = budget or SourceRequestBudget(settings.max_source_requests)
    try:
        with httpx.Client(
            timeout=settings.source_request_timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "Kabtak/0.2 (+local scholarship evidence checker)"},
        ) as client:
            while True:
                policy = match_source_policy(programme, current_url)
                if policy is None:
                    raise UnsupportedSourceError(
                        "Source URL is outside the reviewed programme policy"
                    )
                _require_public_host(current_url)
                request_budget.consume()

                with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        redirect_count += 1
                        if redirect_count > MAX_REDIRECTS:
                            raise SourceUnavailableError("Source redirect budget exceeded")
                        location = response.headers.get("location")
                        if not location:
                            raise SourceUnavailableError(
                                "Source redirect did not include a location"
                            )
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code >= 500:
                        raise SourceUnavailableError(f"Source returned HTTP {response.status_code}")
                    if response.status_code >= 400:
                        raise SourceUnavailableError(f"Source returned HTTP {response.status_code}")
                    declared_length = response.headers.get("content-length")
                    if (
                        declared_length
                        and declared_length.isdigit()
                        and int(declared_length) > MAX_SOURCE_BYTES
                    ):
                        raise UnsupportedSourceError("Source exceeded the 10 MB limit")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_SOURCE_BYTES:
                            raise UnsupportedSourceError("Source exceeded the 10 MB limit")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    if not content:
                        raise SourceUnavailableError("Source returned an empty response")
                    resolved_url = str(response.url)
                    final_policy = match_source_policy(programme, resolved_url)
                    if final_policy is None:
                        raise UnsupportedSourceError(
                            "Source resolved outside the reviewed programme policy"
                        )
                    content_type = _validate_content_type(
                        response.headers.get("content-type", ""), resolved_url, content
                    )
                    source_format = "pdf" if content_type == "application/pdf" else "html"
                    if source_format not in final_policy.get("formats", ["html", "pdf"]):
                        raise UnsupportedSourceError(
                            "Source format is not approved by its programme policy"
                        )
                    return RetrievedSource(
                        requested_url=requested_url,
                        resolved_url=resolved_url,
                        content=content,
                        content_type=content_type,
                        sha256=hashlib.sha256(content).hexdigest(),
                        retrieved_at=datetime.now(UTC),
                        source_policy=final_policy,
                    )
    except (UnsupportedSourceError, SourceUnavailableError):
        raise
    except (httpx.TimeoutException, httpx.NetworkError):
        raise SourceUnavailableError("Source request timed out or failed") from None
    except httpx.HTTPError:
        raise SourceUnavailableError("Source request failed") from None
