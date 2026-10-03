"""Allowlisted and size-limited source retrieval."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.config import Settings
from app.services.registry import match_source_policy

MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3


@dataclass(frozen=True)
class RetrievedSource:
    requested_url: str
    resolved_url: str
    content: bytes
    content_type: str
    sha256: str
    source_policy: dict[str, Any]


def _require_public_host(url: str) -> None:
    hostname = urlparse(url).hostname
    if not hostname:
        raise RuntimeError("Source URL has no hostname")
    addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    if not addresses:
        raise RuntimeError("Source hostname did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise RuntimeError("Source hostname resolved to a non-public address")


def retrieve_source(
    settings: Settings, programme: dict[str, Any], requested_url: str
) -> RetrievedSource:
    current_url = requested_url
    request_count = 0
    with httpx.Client(
        timeout=settings.source_request_timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": "Kabtak/0.1 (+local scholarship evidence checker)"},
    ) as client:
        while True:
            policy = match_source_policy(programme, current_url)
            if policy is None:
                raise RuntimeError("Source URL is outside the reviewed programme policy")
            _require_public_host(current_url)
            request_count += 1
            if request_count > min(settings.max_source_requests, MAX_REDIRECTS + 1):
                raise RuntimeError("Source redirect budget exceeded")

            with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("Source redirect did not include a location")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_SOURCE_BYTES:
                        raise RuntimeError("Source exceeded the 10 MB limit")
                    chunks.append(chunk)
                content = b"".join(chunks)
                content_type = response.headers.get("content-type", "")
                resolved_url = str(response.url)
                final_policy = match_source_policy(programme, resolved_url)
                if final_policy is None:
                    raise RuntimeError("Source resolved outside the reviewed programme policy")
                return RetrievedSource(
                    requested_url=requested_url,
                    resolved_url=resolved_url,
                    content=content,
                    content_type=content_type,
                    sha256=hashlib.sha256(content).hexdigest(),
                    source_policy=final_policy,
                )
