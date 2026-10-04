"""Bounded HTML/PDF parsing into immutable, hashed evidence blocks."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import queue
import re
import tempfile
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import pdfplumber
from bs4 import BeautifulSoup, Tag

from app.services.failures import ParsingFailedError, ProcessingError, UnsupportedPDFError

PARSER_VERSION = "phase2-3"
SPACE_PATTERN = re.compile(r"\s+")
SELECTED_HTML_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"}
ACADEMIC_YEAR_PATTERN = re.compile(r"\bacademic\s+year\s+\d{4}\s*[-–]\s*\d{2}\b", re.I)


@dataclass(frozen=True)
class Block:
    block_id: str
    kind: str
    location: str
    text: str
    text_sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_text(value: str) -> str:
    return SPACE_PATTERN.sub(" ", value).strip()


def _is_nsp_scheme_card(element: Tag) -> bool:
    """Recognize one National Scholarship Portal scheme/schedule card."""

    classes = set(element.get("class", []))
    return (
        element.name == "div"
        and {"row", "border-bottom"}.issubset(classes)
        and element.find("h6") is not None
    )


def _is_inside_nsp_scheme_card(element: Tag) -> bool:
    return any(
        isinstance(parent, Tag) and _is_nsp_scheme_card(parent) for parent in element.parents
    )


def _make_block(
    blocks: list[Block],
    *,
    kind: str,
    location: str,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not text:
        return
    blocks.append(
        Block(
            block_id=f"block_{len(blocks) + 1}",
            kind=kind,
            location=location,
            text=text,
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            metadata=metadata or {},
        )
    )


def parse_html(content: bytes) -> list[Block]:
    soup = BeautifulSoup(content, "html.parser")
    # Some official portals put the active cycle inside navigation that is otherwise
    # intentionally discarded as page chrome. Preserve only the bounded cycle label
    # before removing navigation; without it, otherwise valid scheme cards lose the
    # evidence needed to bind their dates to an academic year.
    document_context = list(
        dict.fromkeys(
            normalize_text(match.group())
            for text in soup.find_all(string=ACADEMIC_YEAR_PATTERN)
            for match in ACADEMIC_YEAR_PATTERN.finditer(str(text))
        )
    )
    for unwanted in soup.select("script, style, noscript, svg, nav, footer"):
        unwanted.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    blocks: list[Block] = []
    for context in document_context:
        _make_block(
            blocks,
            kind="document_context",
            location="document metadata",
            text=context,
        )
    section = "document"
    table_number = 0
    for element in root.find_all([*SELECTED_HTML_TAGS, "div"]):
        if not isinstance(element, Tag):
            continue
        scheme_card = _is_nsp_scheme_card(element)
        if element.name == "div" and not scheme_card:
            continue
        if not scheme_card and _is_inside_nsp_scheme_card(element):
            continue
        if element.name != "table" and element.find_parent("table") is not None:
            continue
        if element.name == "li" and element.find_parent("li") is not None:
            continue
        if scheme_card:
            title_element = element.find("h6")
            title = normalize_text(title_element.get_text(" ", strip=True))
            details = [
                normalize_text(item.get_text(" ", strip=True)) for item in element.find_all("span")
            ]
            text = "\n".join([title, *(detail for detail in details if detail)])
            _make_block(
                blocks,
                kind="scheme_card",
                location=f"scheme {title[:160]}",
                text=text,
            )
            continue
        if element.name == "table":
            table_number += 1
            structured_rows: list[list[str]] = []
            headers: list[str] = []
            for row_index, row in enumerate(element.find_all("tr")):
                cells = [
                    normalize_text(cell.get_text(" ", strip=True))
                    for cell in row.find_all(["th", "td"])
                ]
                if not any(cells):
                    continue
                structured_rows.append(cells)
                if row.find("th") is not None and (row_index == 0 or not headers):
                    headers = cells
            if not headers and structured_rows:
                # Government pages commonly style header cells without semantic
                # <th> tags. Keep the first row separately as header context while
                # retaining it in the complete ordered row list.
                headers = structured_rows[0]
            text = "\n".join(" | ".join(row) for row in structured_rows)
            _make_block(
                blocks,
                kind="table",
                location=f"section {section}, table {table_number}",
                text=text,
                metadata={"headers": headers, "rows": structured_rows},
            )
            continue

        text = normalize_text(element.get_text(" ", strip=True))
        kind = "heading" if element.name.startswith("h") else element.name
        if kind == "heading" and text:
            section = text[:120]
        _make_block(blocks, kind=kind, location=f"section {section}", text=text)
    if not blocks:
        raise ParsingFailedError("HTML source contained no readable evidence blocks")
    return blocks


def _normalize_table(table: list[list[str | None]] | None) -> list[list[str]]:
    if not table:
        return []
    rows: list[list[str]] = []
    for raw_row in table:
        row = [normalize_text(cell or "") for cell in raw_row]
        if any(row):
            rows.append(row)
    return rows


def parse_pdf(content: bytes, max_pages: int = 20) -> tuple[list[Block], bool]:
    blocks: list[Block] = []
    try:
        with pdfplumber.open(BytesIO(content)) as document:
            partial = len(document.pages) > max_pages
            for page_number, page in enumerate(document.pages[:max_pages], start=1):
                text = normalize_text(page.extract_text() or "")
                _make_block(
                    blocks,
                    kind="page_text",
                    location=f"page {page_number}",
                    text=text,
                    metadata={"page": page_number},
                )
                for table_number, raw_table in enumerate(page.extract_tables(), start=1):
                    rows = _normalize_table(raw_table)
                    table_text = "\n".join(" | ".join(row) for row in rows)
                    _make_block(
                        blocks,
                        kind="table",
                        location=f"page {page_number}, table {table_number}",
                        text=table_text,
                        metadata={
                            "page": page_number,
                            "headers": rows[0] if rows else [],
                            "rows": rows,
                        },
                    )
    except Exception:
        raise UnsupportedPDFError("PDF library could not open or parse the document") from None
    if not blocks:
        raise UnsupportedPDFError("PDF has no extractable text; scanned PDFs require OCR")
    return blocks, partial


def parse_source(content: bytes, content_type: str, url: str, max_pages: int = 20):
    is_pdf = content_type == "application/pdf" or urlparse_suffix(url) == ".pdf"
    if is_pdf:
        blocks, partial = parse_pdf(content, max_pages=max_pages)
        return blocks, "pdf", "partial_page_limit" if partial else "parsed"
    try:
        return parse_html(content), "html", "parsed"
    except ProcessingError:
        raise
    except Exception:
        raise ParsingFailedError("HTML parser failed") from None


def _parse_worker(
    result_queue: Any,
    content: bytes,
    content_type: str,
    url: str,
    max_pages: int,
) -> None:
    try:
        result_queue.put(("ok", parse_source(content, content_type, url, max_pages)))
    except ProcessingError as exc:
        result_queue.put(("error", exc.code, exc.public_message, exc.retryable, type(exc).__name__))
    except Exception as exc:  # noqa: BLE001 - child errors become a safe parser state.
        result_queue.put(("error", "PARSING_FAILED", str(exc), False, type(exc).__name__))


def parse_source_bounded(
    content: bytes,
    content_type: str,
    url: str,
    *,
    max_pages: int = 20,
    timeout_seconds: int = 10,
) -> tuple[list[Block], str, str]:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_parse_worker,
        args=(result_queue, content, content_type, url, max_pages),
        daemon=True,
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(2)
        raise ParsingFailedError("Source parsing exceeded the time limit")
    try:
        result = result_queue.get(timeout=1)
    except queue.Empty:
        raise ParsingFailedError("Parser process exited without a result") from None
    finally:
        result_queue.close()
    if result[0] == "ok":
        return result[1]
    _status, code, message, retryable, diagnostic = result
    if code == "UNSUPPORTED_PDF":
        raise UnsupportedPDFError(diagnostic)
    raise ProcessingError(code, message, retryable=retryable, diagnostic=diagnostic)


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
    blocks_path = source_dir / f"{stem}-{PARSER_VERSION}.blocks.json"
    _atomic_write_once(original_path, content)
    _atomic_write_once(
        blocks_path,
        (
            json.dumps([asdict(block) for block in blocks], indent=2, ensure_ascii=False) + "\n"
        ).encode(),
    )
    return str(original_path), str(blocks_path)


def _atomic_write_once(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ParsingFailedError("Immutable evidence path already contains different bytes")
        return
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".source-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ParsingFailedError(
                    "Immutable evidence path was concurrently written with different bytes"
                ) from None
        Path(temporary_name).unlink(missing_ok=True)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
