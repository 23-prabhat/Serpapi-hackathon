"""Source-bound facts used by deterministic decision rules."""

from dataclasses import dataclass

from app.services.extraction import ExtractedFacts


@dataclass(frozen=True)
class SourcedRecord:
    record: ExtractedFacts
    version_id: str
    source_capabilities: frozenset[str]
    parse_status: str = "parsed"
    document_unresolved_items: tuple[str, ...] = ()
