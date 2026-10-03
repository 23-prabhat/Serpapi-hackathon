"""Integrity and ownership checks for report evidence references."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DocumentVersion, RunDocument
from app.services.extraction import date_occurs_in_text
from app.services.failures import InvalidExtractionError


def load_version_blocks(version: DocumentVersion) -> list[dict[str, Any]]:
    original_path = Path(version.original_path)
    blocks_path = Path(version.parsed_blocks_path)
    try:
        original = original_path.read_bytes()
        blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise InvalidExtractionError(
            "Preserved evidence files are unavailable or invalid"
        ) from None
    if hashlib.sha256(original).hexdigest() != version.sha256:
        raise InvalidExtractionError("Preserved source bytes do not match the version hash")
    if not isinstance(blocks, list):
        raise InvalidExtractionError("Preserved evidence blocks are not a list")
    for block in blocks:
        if not isinstance(block, dict) or not all(
            isinstance(block.get(field), str) for field in ("block_id", "kind", "location", "text")
        ):
            raise InvalidExtractionError("Preserved evidence block has an invalid shape")
        expected_hash = block.get("text_sha256")
        actual_hash = hashlib.sha256(block["text"].encode()).hexdigest()
        if expected_hash is not None and expected_hash != actual_hash:
            raise InvalidExtractionError("Preserved evidence block failed its hash check")
    return blocks


def validate_report_evidence(
    session: Session,
    run_id: str,
    report_json: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    associations = session.scalars(
        select(RunDocument).where(
            RunDocument.run_id == run_id,
            RunDocument.document_version_id.is_not(None),
        )
    ).all()
    versions: dict[str, DocumentVersion] = {}
    for association in associations:
        if association.document_version_id is None:
            continue
        version = session.get(DocumentVersion, association.document_version_id)
        if version is None:
            raise InvalidExtractionError("Run evidence references a missing document version")
        if (
            association.extraction is not None
            and association.extraction.document_version_id != association.document_version_id
        ):
            raise InvalidExtractionError("Extraction belongs to a different document version")
        versions[version.id] = version

    block_index: dict[tuple[str, str], dict[str, Any]] = {}
    for version_id, version in versions.items():
        for block in load_version_blocks(version):
            key = (version_id, block["block_id"])
            if key in block_index:
                raise InvalidExtractionError("Evidence contains a duplicate block identifier")
            block_index[key] = block

    deadlines = []
    if report_json.get("student_deadline"):
        deadlines.append(report_json["student_deadline"])
    deadlines.extend(report_json.get("other_deadlines", []))
    for conflict in report_json.get("conflicts", []):
        deadlines.extend(conflict.get("candidates", []))
    for deadline in deadlines:
        cited_blocks = _resolve_references(deadline.get("evidence_refs", []), block_index)
        if not any(date_occurs_in_text(deadline["date"], block["text"]) for block in cited_blocks):
            raise InvalidExtractionError("Reported date does not occur in its cited evidence")

    for amendment in report_json.get("amendments", []):
        previous_blocks = _resolve_references(
            amendment.get("previous_evidence_refs", []), block_index
        )
        revised_blocks = _resolve_references(
            amendment.get("revised_evidence_refs", []), block_index
        )
        if not any(
            date_occurs_in_text(amendment["previous_date"], block["text"])
            for block in previous_blocks
        ):
            raise InvalidExtractionError(
                "Reported previous amendment date does not occur in its cited evidence"
            )
        if not any(
            date_occurs_in_text(amendment["revised_date"], block["text"])
            for block in revised_blocks
        ):
            raise InvalidExtractionError(
                "Reported revised amendment date does not occur in its cited evidence"
            )

    for condition in report_json.get("conditions", []):
        _validate_condition(condition, block_index)
    for requirement in report_json.get("required_documents", []):
        _validate_sourced_text(requirement, block_index, "Required-document")
    for link in report_json.get("application_links", []):
        cited_blocks = _validate_sourced_text(link, block_index, "Application-link")
        if not any(str(link.get("url", "")) in block["text"] for block in cited_blocks):
            raise InvalidExtractionError("Application link does not occur in cited evidence")
    return block_index


def _resolve_references(
    references: list[dict[str, Any]],
    block_index: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    if not references:
        raise InvalidExtractionError("A reported conclusion has no evidence references")
    cited_blocks: list[dict[str, Any]] = []
    for reference in references:
        key = (reference.get("version_id"), reference.get("block_id"))
        block = block_index.get(key)
        if block is None:
            raise InvalidExtractionError(
                "Report cited a block outside the document versions used by this run"
            )
        cited_blocks.append(block)
    return cited_blocks


def _validate_condition(
    condition: dict[str, Any],
    block_index: dict[tuple[str, str], dict[str, Any]],
) -> None:
    cited_blocks = _resolve_references(condition.get("evidence_refs", []), block_index)
    source_text = " ".join(str(condition.get("source_text", "")).casefold().split())
    if not source_text or not any(
        source_text in " ".join(block["text"].casefold().split()) for block in cited_blocks
    ):
        raise InvalidExtractionError("Reported condition text does not occur in cited evidence")
    for child in condition.get("children", []):
        _validate_condition(child, block_index)


def _validate_sourced_text(
    item: dict[str, Any],
    block_index: dict[tuple[str, str], dict[str, Any]],
    label: str,
) -> list[dict[str, Any]]:
    cited_blocks = _resolve_references(item.get("evidence_refs", []), block_index)
    source_text = " ".join(str(item.get("source_text", "")).casefold().split())
    if not source_text or not any(
        source_text in " ".join(block["text"].casefold().split()) for block in cited_blocks
    ):
        raise InvalidExtractionError(f"{label} text does not occur in cited evidence")
    return cited_blocks
