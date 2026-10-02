"""Bounded Phase 0 probe for reviewed HTML and text-PDF sources.

This script intentionally accepts sources only from the checked-in manifest. It
is an experiment, not the production retrieval implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pdfplumber
import yaml
from bs4 import BeautifulSoup, Tag

DEADLINE_PATTERN = re.compile(
    r"\b(deadline|last date|closing date|open till|closed on|submission|"
    r"verification|correction|apply|application)\b",
    re.IGNORECASE,
)
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


def is_scheme_card(element: Tag) -> bool:
    classes = set(element.get("class", []))
    return (
        element.name == "div"
        and {"row", "border-bottom"}.issubset(classes)
        and bool(element.find("h6"))
    )


def is_inside_scheme_card(element: Tag) -> bool:
    return any(isinstance(parent, Tag) and is_scheme_card(parent) for parent in element.parents)


def parse_html(content: bytes) -> list[Block]:
    soup = BeautifulSoup(content, "html.parser")
    for unwanted in soup.select("script, style, noscript, svg, nav, footer"):
        unwanted.decompose()

    root = soup.find("main") or soup.find("article") or soup.body or soup
    blocks: list[Block] = []
    section = "document"
    table_number = 0

    for element in root.find_all([*SELECTED_HTML_TAGS, "div"]):
        if not isinstance(element, Tag):
            continue
        scheme_card = is_scheme_card(element)
        if element.name == "div" and not scheme_card:
            continue
        if not scheme_card and is_inside_scheme_card(element):
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
            details = [detail for detail in details if detail]
            text = "\n".join([title, *details])
            kind = "scheme_card"
            location = f"scheme {title[:160]}"
        elif element.name == "table":
            table_number += 1
            rows: list[str] = []
            for row in element.find_all("tr"):
                cells = [
                    normalize_text(cell.get_text(" ", strip=True))
                    for cell in row.find_all(["th", "td"])
                ]
                cells = [cell for cell in cells if cell]
                if cells:
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


def parse_pdf(content: bytes, max_pages: int) -> tuple[list[Block], int]:
    blocks: list[Block] = []
    with pdfplumber.open(BytesIO(content)) as document:
        page_count = len(document.pages)
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
            for table_number, table in enumerate(page.extract_tables(), start=1):
                rows = []
                for row in table:
                    cells = [normalize_text(cell or "") for cell in row]
                    if any(cells):
                        rows.append(" | ".join(cells))
                table_text = "\n".join(rows)
                if table_text:
                    blocks.append(
                        Block(
                            block_id=f"block_{len(blocks) + 1}",
                            kind="table",
                            location=f"page {page_number}, table {table_number}",
                            text=table_text,
                        )
                    )
    return blocks, page_count


def bounded_excerpt(text: str, limit: int = 320) -> str:
    normalized = normalize_text(text)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def probe_source(
    client: httpx.Client,
    source: dict[str, Any],
    raw_dir: Path,
    max_bytes: int,
    max_pdf_pages: int,
) -> dict[str, Any]:
    started = datetime.now(UTC)
    result: dict[str, Any] = {
        "id": source["id"],
        "programme_id": source["programme_id"],
        "cycle": source["cycle"],
        "url": source["url"],
        "format": source["format"],
        "expected_topics": source["expected_topics"],
    }
    try:
        with client.stream("GET", source["url"]) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"source exceeds {max_bytes} bytes")
                chunks.append(chunk)
            content = b"".join(chunks)
            result["status_code"] = response.status_code
            result["final_url"] = str(response.url)
            result["content_type"] = response.headers.get("content-type")

        digest = hashlib.sha256(content).hexdigest()
        suffix = ".pdf" if source["format"] == "pdf" else ".html"
        raw_path = raw_dir / f"{source['id']}-{digest[:12]}{suffix}"
        raw_path.write_bytes(content)

        if source["format"] == "pdf":
            blocks, page_count = parse_pdf(content, max_pdf_pages)
            result["page_count"] = page_count
            result["pages_processed"] = min(page_count, max_pdf_pages)
            result["coverage"] = "complete" if page_count <= max_pdf_pages else "partial_page_limit"
        else:
            blocks = parse_html(content)
            result["coverage"] = "complete"

        parsed_path = raw_dir / f"{source['id']}-{digest[:12]}.blocks.json"
        parsed_path.write_text(
            json.dumps([asdict(block) for block in blocks], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        candidates = [block for block in blocks if DEADLINE_PATTERN.search(block.text)]
        result.update(
            {
                "outcome": "parsed",
                "sha256": digest,
                "bytes": len(content),
                "block_count": len(blocks),
                "table_block_count": sum(block.kind == "table" for block in blocks),
                "deadline_candidate_count": len(candidates),
                "candidate_samples": [
                    {
                        "block_id": block.block_id,
                        "kind": block.kind,
                        "location": block.location,
                        "excerpt": bounded_excerpt(block.text),
                    }
                    for block in candidates[:8]
                ],
            }
        )
    except Exception as exc:  # noqa: BLE001 - preserve every per-source probe failure.
        result.update(
            {
                "outcome": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }
        )
    result["elapsed_ms"] = int((datetime.now(UTC) - started).total_seconds() * 1000)
    return result


def run(manifest_path: Path, output_path: Path, raw_dir: Path) -> dict[str, Any]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    limits = manifest["limits"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "KabtakPhase0Probe/0.1 (+local source compatibility test)"}
    with httpx.Client(
        follow_redirects=True,
        timeout=limits["timeout_seconds"],
        headers=headers,
    ) as client:
        source_results = [
            probe_source(
                client,
                source,
                raw_dir,
                limits["max_bytes"],
                limits["max_pdf_pages"],
            )
            for source in manifest["sources"]
        ]

    result = {
        "schema_version": 1,
        "manifest_reference_time": manifest["reference_time"],
        "probed_at": datetime.now(UTC).isoformat(),
        "parser_version": "phase0-1",
        "summary": {
            "source_count": len(source_results),
            "parsed": sum(item["outcome"] == "parsed" for item in source_results),
            "failed": sum(item["outcome"] == "failed" for item in source_results),
            "partial": sum(item.get("coverage") == "partial_page_limit" for item in source_results),
            "programmes_with_parsed_source": sorted(
                {item["programme_id"] for item in source_results if item["outcome"] == "parsed"}
            ),
        },
        "sources": source_results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    phase0_dir = Path(__file__).resolve().parent
    kabtak_dir = phase0_dir.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=phase0_dir / "sources.yaml")
    parser.add_argument(
        "--output",
        type=Path,
        default=phase0_dir / "results" / "probe-results.json",
    )
    parser.add_argument("--raw-dir", type=Path, default=kabtak_dir / "data" / "phase0")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run(args.manifest, args.output, args.raw_dir)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
