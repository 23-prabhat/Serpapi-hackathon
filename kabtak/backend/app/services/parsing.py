"""HTML and text-PDF parsing into ordered evidence blocks."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path

import pdfplumber
from bs4 import BeautifulSoup, Tag

PARSER_VERSION = "phase1-1"
SPACE_PATTERN = re.compile(r"\s+")
SELECTED_HTML_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"}


@dataclass(frozen=True)
class Block:
    block_id: str
    kind: str
    location: str
    text: str


def normalize_text(value: str) -> str:
    return SPACE_PATTERN.sub(" ", value).strip()


def parse_html(content: bytes) -> list[Block]:
    soup = BeautifulSoup(content, "html.parser")
    for unwanted in soup.select("script, style, noscript, svg, nav, footer"):
        unwanted.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    blocks: list[Block] = []
    section = "document"
    table_number = 0
    for element in root.find_all(SELECTED_HTML_TAGS):
        if not isinstance(element, Tag):
            continue
        if element.name != "table" and element.find_parent("table") is not None:
            continue
        if element.name == "li" and element.find_parent("li") is not None:
            continue
        if element.name == "table":
            table_number += 1
            rows: list[str] = []
            for row in element.find_all("tr"):
                cells = [
                    normalize_text(cell.get_text(" ", strip=True))
                    for cell in row.find_all(["th", "td"])
                ]
                if any(cells):
                    rows.append(" | ".join(cells))
            text = "\n".join(rows)
            kind = "table"
            location = f"section {section}, table {table_number}"
        else:
            text = normalize_text(element.get_text(" ", strip=True))
            kind = "heading" if element.name.startswith("h") else element.name
            if kind == "heading" and text:
                section = text[:120]
            location = f"section {section}"
        if text:
            blocks.append(
                Block(
                    block_id=f"block_{len(blocks) + 1}",
                    kind=kind,
                    location=location,
                    text=text,
                )
            )
    return blocks


def parse_pdf(content: bytes, max_pages: int = 20) -> tuple[list[Block], bool]:
    blocks: list[Block] = []
    with pdfplumber.open(BytesIO(content)) as document:
        partial = len(document.pages) > max_pages
        for page_number, page in enumerate(document.pages[:max_pages], start=1):
            text = normalize_text(page.extract_text() or "")
            if text:
                blocks.append(
                    Block(
                        block_id=f"block_{len(blocks) + 1}",
                        kind="page_text",
                        location=f"page {page_number}",
                        text=text,
                    )
                )
    return blocks, partial


def parse_source(content: bytes, content_type: str, url: str) -> tuple[list[Block], str, str]:
    is_pdf = "pdf" in content_type.lower() or urlparse_suffix(url) == ".pdf"
    if is_pdf:
        blocks, partial = parse_pdf(content)
        return blocks, "pdf", "partial_page_limit" if partial else "parsed"
    return parse_html(content), "html", "parsed"


def urlparse_suffix(url: str) -> str:
    from urllib.parse import urlparse

    return Path(urlparse(url).path).suffix.lower()


def persist_source_files(
    data_dir: Path,
    source_id: str,
    digest: str,
    content: bytes,
    source_format: str,
    blocks: list[Block],
) -> tuple[str, str]:
    source_dir = data_dir.resolve() / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{source_id}-{digest[:16]}"
    original_path = source_dir / f"{stem}.{source_format}"
    blocks_path = source_dir / f"{stem}.blocks.json"
    _atomic_bytes(original_path, content)
    _atomic_bytes(
        blocks_path,
        (
            json.dumps([asdict(block) for block in blocks], indent=2, ensure_ascii=False) + "\n"
        ).encode(),
    )
    return str(original_path), str(blocks_path)


def _atomic_bytes(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".source-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
