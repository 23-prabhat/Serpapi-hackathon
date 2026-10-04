"""Run the Phase 5 system evaluation and the single-prompt baseline.

The system path calls the production structured extractor once per preserved
document, then applies the current deterministic report rules to every case.
The baseline makes one independent model call per case over the same blocks.
Completed model calls are checkpointed so free-plan rate limits do not lose work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

import httpx
import yaml

PHASE5_DIR = Path(__file__).resolve().parent
KABTAK_DIR = PHASE5_DIR.parents[1]
BACKEND_DIR = KABTAK_DIR / "backend"
RESULTS_DIR = PHASE5_DIR / "results"
EXTRACTIONS_PATH = RESULTS_DIR / "system-extractions.json"
SYSTEM_RESULTS_PATH = RESULTS_DIR / "system-results.json"
BASELINE_RESULTS_PATH = RESULTS_DIR / "baseline-results.json"
BASELINE_CHECKPOINT_PATH = RESULTS_DIR / ".baseline-checkpoint.json"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_SYSTEM_CALLS = 11
MAX_BASELINE_CALLS = 20
FREE_TIER_TOKEN_WINDOW_SECONDS = 25
BASELINE_TOKEN_WINDOW_SECONDS = 15

sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings  # noqa: E402
from app.schemas.reports import ReportRead  # noqa: E402
from app.services.extraction import (  # noqa: E402
    ExtractedDocument,
    date_occurs_in_text,
    extract_facts,
    prompt_hash,
)
from app.services.parsing import Block  # noqa: E402
from app.services.registry import load_registry  # noqa: E402
from app.services.reporting import build_report  # noqa: E402
from app.services.rules.types import SourcedRecord  # noqa: E402

BASELINE_PROMPT = """You are a simple scholarship-document summarizer. Answer the requested
case only from the supplied official-source blocks. Keep student submission,
student correction, institution verification, and administrator verification
separate. Do not turn a later correction or verification date into a submission
extension. If two applicable student dates conflict and neither passage explicitly
revises the other, return conflicting with no selected deadline. If an exact date
or scope is absent, return insufficient. Evaluate only conditions present in the
blocks against the supplied profile. Use not_assessed when no profile was supplied
and more_information_needed when a profile was supplied but the blocks do not
establish enough eligibility conditions. Cite exact source_id:block_id values.
For a date-only deadline on the reference date, timing is due_today_time_unknown.
Always return the complete output even when the question emphasizes one field.
For supported results, student_deadline must contain the selected submission date
and candidate_dates must be empty. Use candidate_dates only for unresolved,
conflicting student-submission dates."""

BASELINE_DEADLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "actor": {
            "type": "string",
            "enum": ["student", "institution", "administrator", "unknown"],
        },
        "action": {
            "type": "string",
            "enum": ["submit", "correct", "verify", "other", "unknown"],
        },
        "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "timing": {
            "type": "string",
            "enum": [
                "date_ahead",
                "due_today_time_unknown",
                "date_passed",
                "before_cutoff",
                "after_cutoff",
                "unknown",
            ],
        },
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
    },
    "required": ["actor", "action", "date", "timing", "evidence_refs"],
}

BASELINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "deadline_resolution": {
            "type": "string",
            "enum": ["supported", "conflicting", "insufficient"],
        },
        "student_deadline": {"anyOf": [BASELINE_DEADLINE_SCHEMA, {"type": "null"}]},
        "other_deadlines": {"type": "array", "items": BASELINE_DEADLINE_SCHEMA},
        "candidate_dates": {
            "type": "array",
            "items": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        },
        "eligibility": {
            "type": "string",
            "enum": [
                "meets_checked_conditions",
                "condition_not_met",
                "more_information_needed",
                "not_assessed",
            ],
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "deadline_resolution",
        "student_deadline",
        "other_deadlines",
        "candidate_dates",
        "eligibility",
        "limitations",
    ],
}


def canonical_hash(value: Any) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(rendered.encode()).hexdigest()


def load_inputs() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest = yaml.safe_load((PHASE5_DIR / "cases.yaml").read_text(encoding="utf-8"))
    source_manifest = yaml.safe_load((PHASE5_DIR / "sources.yaml").read_text(encoding="utf-8"))
    cases = manifest["cases"]
    sources = {source["id"]: source for source in source_manifest["documents"]}
    return cases, sources


def load_settings() -> Settings:
    return Settings(_env_file=BACKEND_DIR / ".env")


def source_blocks(source: dict[str, Any]) -> list[Block]:
    return [
        Block(
            block_id=item["block_id"],
            kind=item["kind"],
            location=item["location"],
            text=item["text"],
            text_sha256=hashlib.sha256(item["text"].encode()).hexdigest(),
            metadata=item.get("metadata", {}),
        )
        for item in source["blocks"]
    ]


def run_system_extractions(
    settings: Settings,
    sources: dict[str, dict[str, Any]],
    *,
    offline: bool,
) -> dict[str, Any]:
    cached: dict[str, Any] = {
        "schema_version": 3,
        "model": settings.llm_model,
        "prompt_sha256": prompt_hash(),
        "documents": {},
    }
    if EXTRACTIONS_PATH.exists():
        existing = json.loads(EXTRACTIONS_PATH.read_text(encoding="utf-8"))
        if (
            existing.get("schema_version") == 3
            and existing.get("model") == settings.llm_model
            and existing.get("prompt_sha256") == prompt_hash()
        ):
            cached = existing

    cases = load_inputs()[0]
    required_inputs = sorted(
        {
            (source_id, case["application_type"])
            for case in cases
            for source_id in case["source_ids"]
        }
    )
    if len(required_inputs) > MAX_SYSTEM_CALLS:
        raise RuntimeError("System extraction call budget exceeded")
    for source_id, application_type in required_inputs:
        cache_key = f"{source_id}::{application_type}"
        if cache_key in cached["documents"]:
            continue
        if offline:
            raise RuntimeError(f"Offline extraction cache is missing {cache_key}")
        source = sources[source_id]
        programme = load_registry()[source["programme_id"]]
        cycle = next(
            case["academic_year"]
            for case in cases
            if source_id in case["source_ids"] and case["application_type"] == application_type
        )
        started = perf_counter()
        document, usage = extract_facts(
            settings,
            programme["name"],
            cycle,
            application_type,
            source_blocks(source),
        )
        cached["documents"][cache_key] = {
            "extraction": document.model_dump(mode="json"),
            "usage": usage,
            "elapsed_ms": round((perf_counter() - started) * 1000),
        }
        cached["updated_at"] = datetime.now(UTC).isoformat()
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        EXTRACTIONS_PATH.write_text(
            json.dumps(cached, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"system extraction: {cache_key}")
        sleep(FREE_TIER_TOKEN_WINDOW_SECONDS)
    return cached


def system_report(
    case: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    extractions: dict[str, Any],
    model_id: str,
) -> dict[str, Any]:
    sourced_records: list[SourcedRecord] = []
    for source_id in case["source_ids"]:
        source = sources[source_id]
        cache_key = f"{source_id}::{case['application_type']}"
        document = ExtractedDocument.model_validate(
            extractions["documents"][cache_key]["extraction"]
        )
        for record in document.records:
            sourced_records.append(
                SourcedRecord(
                    record=record,
                    version_id=f"phase5:{source_id}",
                    source_capabilities=frozenset(source["source_capabilities"]),
                    document_unresolved_items=tuple(document.document_unresolved_items),
                )
            )
    programme = load_registry()[case["programme_id"]]
    report = build_report(
        run_id=f"phase5:{case['id']}",
        reference_time=datetime.fromisoformat(case["reference_time"]),
        programme=programme,
        academic_year=case["academic_year"],
        application_type=case["application_type"],
        sources=sourced_records,
        applicant_group=None,
        profile=case["profile"],
        incomplete_source_attempts=False,
        model_id=model_id,
    )
    ReportRead.model_validate(report)
    return report


def report_candidate_dates(report: dict[str, Any]) -> list[str]:
    return sorted(
        {
            date
            for conflict in report.get("conflicts", [])
            for date in conflict.get("candidate_dates", [])
        }
    )


def deadline_key(deadline: dict[str, Any]) -> tuple[str, str, str]:
    return deadline["actor"], deadline["action"], deadline["date"]


def evidence_index(sources: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        f"{source_id}:{block['block_id']}": block["text"]
        for source_id, source in sources.items()
        for block in source["blocks"]
    }


def check_output(
    case: dict[str, Any],
    output: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    *,
    baseline: bool,
) -> dict[str, bool]:
    expected = case["expected"]
    actual_student = output.get("student_deadline")
    expected_student = expected.get("student_deadline")
    checks = {
        "deadline_resolution": output["deadline_resolution"] == expected["deadline_resolution"],
        "student_deadline": (
            actual_student is None
            if expected_student is None
            else actual_student is not None
            and deadline_key(actual_student)
            == (
                expected_student["actor"],
                expected_student["action"],
                expected_student["date"],
            )
        ),
        "other_deadlines": {
            (item["actor"], item["action"], item["date"])
            for item in expected.get("other_deadlines", [])
        }.issubset({deadline_key(item) for item in output.get("other_deadlines", [])}),
        "candidate_dates": sorted(expected.get("candidate_dates", []))
        == (
            sorted(output.get("candidate_dates", []))
            if baseline
            else report_candidate_dates(output)
        ),
        "eligibility": output["eligibility"] == expected["eligibility"],
    }
    if expected_student and expected_student.get("timing"):
        checks["timing"] = (
            actual_student is not None
            and actual_student.get("timing") == expected_student["timing"]
        )
    checks["citation_support"] = citations_are_supported(output, sources, baseline=baseline)
    return checks


def citations_are_supported(
    output: dict[str, Any], sources: dict[str, dict[str, Any]], *, baseline: bool
) -> bool:
    index = evidence_index(sources)
    deadlines = []
    if output.get("student_deadline"):
        deadlines.append(output["student_deadline"])
    deadlines.extend(output.get("other_deadlines", []))
    if not baseline:
        for conflict in output.get("conflicts", []):
            deadlines.extend(conflict.get("candidates", []))
    for deadline in deadlines:
        refs = deadline.get("evidence_refs", [])
        normalized_refs = [
            ref
            if isinstance(ref, str)
            else f"{str(ref['version_id']).removeprefix('phase5:')}:{ref['block_id']}"
            for ref in refs
        ]
        if not normalized_refs or any(ref not in index for ref in normalized_refs):
            return False
        if not any(date_occurs_in_text(deadline["date"], index[ref]) for ref in normalized_refs):
            return False
    return True


def classify(checks: dict[str, bool], output: dict[str, Any]) -> str:
    if output["deadline_resolution"] != "supported":
        return "unresolved"
    return "correct" if all(checks.values()) else "incorrect"


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        outcome: sum(item["outcome"] == outcome for item in results)
        for outcome in ("correct", "incorrect", "unresolved", "failed")
    }
    answered = counts["correct"] + counts["incorrect"]
    answerable = sum(item["answerable"] for item in results)
    answered_answerable = sum(
        item["answerable"] and item["outcome"] in {"correct", "incorrect"} for item in results
    )
    return {
        "case_count": len(results),
        **counts,
        "ground_truth_matches": sum(item.get("ground_truth_match", False) for item in results),
        "answered_accuracy": round(counts["correct"] / answered, 4) if answered else None,
        "answerable_coverage": round(answered_answerable / answerable, 4) if answerable else None,
    }


def evaluate_system(
    cases: list[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    extractions: dict[str, Any],
    model_id: str,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in cases:
        started = perf_counter()
        try:
            output = system_report(case, sources, extractions, model_id)
            checks = check_output(case, output, sources, baseline=False)
            outcome = classify(checks, output)
            item = {
                "case_id": case["id"],
                "split": case["split"],
                "answerable": case["expected"]["answerable"],
                "outcome": outcome,
                "ground_truth_match": all(checks.values()),
                "checks": checks,
                "output": output,
                "elapsed_ms": round((perf_counter() - started) * 1000, 2),
            }
        except Exception as exc:  # Keep one bad case from hiding all denominators.
            item = {
                "case_id": case["id"],
                "split": case["split"],
                "answerable": case["expected"]["answerable"],
                "outcome": "failed",
                "ground_truth_match": False,
                "error_type": type(exc).__name__,
            }
        results.append(item)
    usages = [entry["usage"] for entry in extractions["documents"].values()]
    result = {
        "schema_version": 1,
        "run_at": datetime.now(UTC).isoformat(),
        "evaluation_kind": "held_out_informed_regression",
        "provider": "groq",
        "model": model_id,
        "model_calls": len(usages),
        "serpapi_calls": 0,
        "usage": {
            "total_tokens": sum(item.get("total_tokens", 0) for item in usages),
            "attempt_count": sum(item.get("attempt_count", 0) for item in usages),
        },
        "summary": summarize(results),
        "by_split": {
            split: summarize([item for item in results if item["split"] == split])
            for split in ("development", "held_out")
        },
        "cases": results,
    }
    if persist:
        SYSTEM_RESULTS_PATH.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return result


def render_baseline_input(
    case: dict[str, Any], sources: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, str]]:
    blocks: list[str] = []
    evidence: dict[str, str] = {}
    for source_id in case["source_ids"]:
        for block in sources[source_id]["blocks"]:
            ref = f"{source_id}:{block['block_id']}"
            evidence[ref] = block["text"]
            blocks.append(f"[{ref}] {block['location']}\n{block['text']}")
    request = {
        "programme_id": case["programme_id"],
        "academic_year": case["academic_year"],
        "application_type": case["application_type"],
        "question": case["question"],
        "reference_time": case["reference_time"],
        "profile": case["profile"],
    }
    return (
        "Requested case:\n"
        + json.dumps(request, indent=2)
        + "\n\nOfficial-source blocks:\n"
        + "\n\n".join(blocks),
        evidence,
    )


def call_baseline(settings: Settings, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    request = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": BASELINE_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "phase5_simple_summary",
                "strict": True,
                "schema": BASELINE_SCHEMA,
            },
        },
        "reasoning_effort": "low",
        "temperature": 0,
        "max_completion_tokens": 800,
    }
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(GROQ_CHAT_URL, headers=headers, json=request)
            if response.status_code == 429 and attempt < 3:
                sleep(min(float(response.headers.get("retry-after", "10")), 30))
                continue
            response.raise_for_status()
            payload = response.json()
            return json.loads(payload["choices"][0]["message"]["content"]), payload.get("usage", {})
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            last_error = exc
            if attempt < 3:
                sleep(2 * attempt)
    raise RuntimeError("Groq baseline request failed") from last_error


def evaluate_baseline(
    settings: Settings,
    cases: list[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    *,
    offline: bool,
) -> dict[str, Any]:
    identity = {
        "model": settings.llm_model,
        "prompt_sha256": canonical_hash(BASELINE_PROMPT),
        "schema_sha256": canonical_hash(BASELINE_SCHEMA),
    }
    results: list[dict[str, Any]] = []
    if BASELINE_CHECKPOINT_PATH.exists():
        checkpoint = json.loads(BASELINE_CHECKPOINT_PATH.read_text(encoding="utf-8"))
        if checkpoint.get("identity") == identity:
            results = checkpoint.get("cases", [])
    elif offline and BASELINE_RESULTS_PATH.exists():
        existing = json.loads(BASELINE_RESULTS_PATH.read_text(encoding="utf-8"))
        if existing.get("identity") == identity:
            return existing
    completed = {item["case_id"] for item in results}
    if len(cases) > MAX_BASELINE_CALLS:
        raise RuntimeError("Baseline call budget exceeded")
    for case in cases:
        if case["id"] in completed:
            continue
        if offline:
            raise RuntimeError(f"Offline baseline cache is missing {case['id']}")
        user_prompt, _ = render_baseline_input(case, sources)
        started = perf_counter()
        try:
            output, usage = call_baseline(settings, user_prompt)
            checks = check_output(case, output, sources, baseline=True)
            item = {
                "case_id": case["id"],
                "split": case["split"],
                "answerable": case["expected"]["answerable"],
                "outcome": classify(checks, output),
                "ground_truth_match": all(checks.values()),
                "checks": checks,
                "output": output,
                "usage": usage,
                "elapsed_ms": round((perf_counter() - started) * 1000, 2),
            }
        except Exception as exc:
            item = {
                "case_id": case["id"],
                "split": case["split"],
                "answerable": case["expected"]["answerable"],
                "outcome": "failed",
                "ground_truth_match": False,
                "error_type": type(exc).__name__,
                "usage": {},
            }
        results.append(item)
        BASELINE_CHECKPOINT_PATH.write_text(
            json.dumps({"identity": identity, "cases": results}, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        print(f"baseline: {case['id']} ({item['outcome']})")
        sleep(BASELINE_TOKEN_WINDOW_SECONDS)

    usages = [item.get("usage", {}) for item in results]
    result = {
        "schema_version": 1,
        "run_at": datetime.now(UTC).isoformat(),
        "identity": identity,
        "provider": "groq",
        "model": settings.llm_model,
        "model_calls": len(results),
        "serpapi_calls": 0,
        "usage": {
            "prompt_tokens": sum(item.get("prompt_tokens", 0) for item in usages),
            "completion_tokens": sum(item.get("completion_tokens", 0) for item in usages),
            "total_tokens": sum(item.get("total_tokens", 0) for item in usages),
        },
        "summary": summarize(results),
        "by_split": {
            split: summarize([item for item in results if item["split"] == split])
            for split in ("development", "held_out")
        },
        "cases": results,
    }
    BASELINE_RESULTS_PATH.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    BASELINE_CHECKPOINT_PATH.unlink(missing_ok=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("all", "system", "baseline"), default="all")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    cases, sources = load_inputs()
    settings = load_settings()
    if args.offline:
        if not settings.llm_model and EXTRACTIONS_PATH.exists():
            cached_model = json.loads(EXTRACTIONS_PATH.read_text(encoding="utf-8")).get("model")
            settings = settings.model_copy(update={"llm_model": cached_model})
        if not settings.llm_model:
            raise RuntimeError("Offline Phase 5 artifacts do not identify their model")
    elif (
        not settings.llm_provider
        or settings.llm_provider.casefold() != "groq"
        or not settings.llm_api_key
        or not settings.llm_model
    ):
        raise RuntimeError("Online Phase 5 evaluation requires configured Groq settings")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.mode in {"all", "system"}:
        extractions = run_system_extractions(settings, sources, offline=args.offline)
        system = evaluate_system(
            cases,
            sources,
            extractions,
            settings.llm_model,
            persist=not args.offline,
        )
        print(json.dumps({"system": system["summary"]}, indent=2))
    if args.mode in {"all", "baseline"}:
        baseline = evaluate_baseline(settings, cases, sources, offline=args.offline)
        print(json.dumps({"baseline": baseline["summary"]}, indent=2))


if __name__ == "__main__":
    main()
