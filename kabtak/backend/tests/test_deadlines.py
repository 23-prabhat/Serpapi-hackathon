"""Deterministic deadline scope, role, amendment, conflict, and date tests."""

from datetime import UTC, datetime

from app.services.extraction import CandidateDeadline, ExtractedFacts
from app.services.rules.deadlines import deadline_timing, resolve_deadlines
from app.services.rules.types import SourcedRecord


def deadline(
    actor: str,
    action: str,
    date_iso: str,
    *,
    application_types: list[str] | None = None,
    applicant_group: str | None = None,
    all_groups: bool = True,
    supersedes: str | None = None,
    revises: bool = False,
    block_id: str = "block_1",
) -> CandidateDeadline:
    return CandidateDeadline(
        actor=actor,
        action=action,
        date_raw=date_iso,
        date_iso=date_iso,
        time=None,
        timezone=None,
        application_types=application_types or ["fresh", "renewal"],
        applicant_group=applicant_group,
        applies_to_all_groups=all_groups,
        explicitly_revises_deadline=revises or supersedes is not None,
        supersedes_date_iso=supersedes,
        evidence_block_ids=[block_id],
    )


def facts(deadlines: list[CandidateDeadline], notice_type: str = "original") -> ExtractedFacts:
    return ExtractedFacts(
        academic_year="2026-27",
        application_types=["fresh", "renewal"],
        applicant_group=None,
        applies_to_all_groups=True,
        scope_evidence_block_ids=["scope"],
        notice_type=notice_type,
        deadlines=deadlines,
        conditions=[],
        required_documents=[],
        application_links=[],
        unresolved_items=[],
    )


def resolve(
    value: ExtractedFacts, group: str | None = None, amendment_authorized: bool = True
) -> dict[str, object]:
    return resolve_deadlines(
        [
            SourcedRecord(
                value,
                "version_1",
                frozenset({"deadline", "amendment"} if amendment_authorized else {"deadline"}),
            )
        ],
        datetime(2026, 10, 2, tzinfo=UTC),
        "Asia/Kolkata",
        "2026-27",
        "fresh",
        group,
    )


def test_student_deadline_does_not_use_later_verification_date() -> None:
    result = resolve(
        facts(
            [
                deadline("student", "submit", "2026-10-31"),
                deadline("institution", "verify", "2026-11-15"),
                deadline("administrator", "verify", "2026-11-30"),
            ],
            notice_type="amendment",
        )
    )

    assert result["resolution"] == "supported"
    assert result["selected"]["date"] == "2026-10-31"  # type: ignore[index]
    assert [item["date"] for item in result["other"]] == [  # type: ignore[index]
        "2026-11-15",
        "2026-11-30",
    ]


def test_fresh_and_renewal_deadlines_stay_separate() -> None:
    value = facts(
        [
            deadline("student", "submit", "2026-10-31", application_types=["fresh"]),
            deadline("student", "submit", "2026-11-10", application_types=["renewal"]),
        ]
    )

    result = resolve(value)

    assert result["resolution"] == "supported"
    assert result["selected"]["date"] == "2026-10-31"  # type: ignore[index]


def test_explicit_same_scope_amendment_replaces_previous_date() -> None:
    original = facts([deadline("student", "submit", "2026-10-15", block_id="old")])
    amendment = facts(
        [deadline("student", "submit", "2026-10-31", supersedes="2026-10-15", block_id="new")],
        "amendment",
    )

    result = resolve_deadlines(
        [
            SourcedRecord(original, "version_old", frozenset({"deadline"})),
            SourcedRecord(amendment, "version_new", frozenset({"deadline", "amendment"})),
        ],
        datetime(2026, 10, 2, tzinfo=UTC),
        "Asia/Kolkata",
        "2026-27",
        "fresh",
    )

    assert result["resolution"] == "supported"
    assert result["selected"]["date"] == "2026-10-31"  # type: ignore[index]
    assert result["amendments"] == [  # type: ignore[comparison-overlap]
        {
            "actor": "student",
            "action": "submit",
            "previous_date": "2026-10-15",
            "revised_date": "2026-10-31",
            "previous_evidence_refs": [{"version_id": "version_old", "block_id": "old"}],
            "revised_evidence_refs": [{"version_id": "version_new", "block_id": "new"}],
            "evidence_refs": [
                {"version_id": "version_old", "block_id": "old"},
                {"version_id": "version_new", "block_id": "new"},
            ],
        }
    ]


def test_explicit_extension_without_old_date_replaces_same_scope_candidate() -> None:
    value = facts(
        [
            deadline("student", "submit", "2026-10-15"),
            deadline("student", "submit", "2026-10-31", revises=True),
        ],
        notice_type="amendment",
    )

    result = resolve(value)

    assert result["resolution"] == "supported"
    assert result["selected"]["date"] == "2026-10-31"  # type: ignore[index]
    assert result["amendments"][0]["previous_date"] == "2026-10-15"  # type: ignore[index]


def test_explicit_amendment_chain_selects_the_last_revised_date() -> None:
    original = facts([deadline("student", "submit", "2026-10-15", block_id="original")])
    first_revision = facts(
        [
            deadline(
                "student",
                "submit",
                "2026-10-31",
                supersedes="2026-10-15",
                block_id="first_revision",
            )
        ],
        "amendment",
    )
    second_revision = facts(
        [
            deadline(
                "student",
                "submit",
                "2026-11-10",
                supersedes="2026-10-31",
                block_id="second_revision",
            )
        ],
        "amendment",
    )

    result = resolve_deadlines(
        [
            SourcedRecord(original, "version_1", frozenset({"deadline"})),
            SourcedRecord(first_revision, "version_2", frozenset({"deadline", "amendment"})),
            SourcedRecord(second_revision, "version_3", frozenset({"deadline", "amendment"})),
        ],
        datetime(2026, 10, 2, tzinfo=UTC),
        "Asia/Kolkata",
        "2026-27",
        "fresh",
    )

    assert result["resolution"] == "supported"
    assert result["selected"]["date"] == "2026-11-10"  # type: ignore[index]
    assert [item["previous_date"] for item in result["amendments"]] == [  # type: ignore[index]
        "2026-10-15",
        "2026-10-31",
    ]


def test_recency_without_explicit_amendment_remains_conflicting() -> None:
    result = resolve(
        facts(
            [
                deadline("student", "submit", "2026-10-15", block_id="old"),
                deadline("student", "submit", "2026-10-31", block_id="new"),
            ],
            notice_type="reminder",
        )
    )

    assert result["resolution"] == "conflicting"
    assert result["selected"] is None
    assert result["conflicts"][0]["candidate_dates"] == [  # type: ignore[index]
        "2026-10-15",
        "2026-10-31",
    ]


def test_explicit_claim_from_unauthorized_source_does_not_amend() -> None:
    value = facts(
        [
            deadline("student", "submit", "2026-10-15"),
            deadline("student", "submit", "2026-10-31", supersedes="2026-10-15"),
        ],
        notice_type="amendment",
    )

    result = resolve(value, amendment_authorized=False)

    assert result["resolution"] == "conflicting"
    assert result["amendments"] == []


def test_later_date_for_different_applicant_group_does_not_replace() -> None:
    value = ExtractedFacts(
        academic_year="2026-27",
        application_types=["fresh"],
        applicant_group=None,
        applies_to_all_groups=True,
        scope_evidence_block_ids=["scope"],
        notice_type="amendment",
        deadlines=[
            deadline(
                "student",
                "submit",
                "2026-10-15",
                applicant_group="general",
                all_groups=False,
            ),
            deadline(
                "student",
                "submit",
                "2026-10-31",
                applicant_group="hostel residents",
                all_groups=False,
                supersedes="2026-10-15",
            ),
        ],
        conditions=[],
        required_documents=[],
        application_links=[],
        unresolved_items=[],
    )

    result = resolve(value, "general")

    assert result["resolution"] == "supported"
    assert result["selected"]["date"] == "2026-10-15"  # type: ignore[index]
    assert result["amendments"] == []


def test_unknown_scope_is_not_a_wildcard() -> None:
    value = facts([deadline("student", "submit", "2026-10-31", application_types=["unknown"])])

    result = resolve(value)

    assert result["resolution"] == "insufficient"
    assert result["selected"] is None


def test_date_only_deadline_today_has_unknown_cutoff_time() -> None:
    assert (
        deadline_timing(
            "2026-10-03",
            datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
            "Asia/Kolkata",
        )
        == "due_today_time_unknown"
    )


def test_same_deadline_from_two_versions_merges_evidence() -> None:
    first = facts([deadline("student", "submit", "2026-10-31", block_id="first")])
    second = facts([deadline("student", "submit", "2026-10-31", block_id="second")])

    result = resolve_deadlines(
        [
            SourcedRecord(first, "version_1", frozenset({"deadline"})),
            SourcedRecord(second, "version_2", frozenset({"deadline"})),
        ],
        datetime(2026, 10, 2, tzinfo=UTC),
        "Asia/Kolkata",
        "2026-27",
        "fresh",
    )

    assert result["resolution"] == "supported"
    assert result["selected"]["evidence_refs"] == [  # type: ignore[index]
        {"version_id": "version_1", "block_id": "first"},
        {"version_id": "version_2", "block_id": "second"},
    ]


def test_explicit_time_and_timezone_are_preserved_and_compared() -> None:
    item = deadline("student", "submit", "2026-10-03")
    item.time = "23:59"
    item.timezone = "Asia/Kolkata"

    result = resolve_deadlines(
        [SourcedRecord(facts([item]), "version_1", frozenset({"deadline"}))],
        datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
        "Asia/Kolkata",
        "2026-27",
        "fresh",
    )

    assert result["selected"]["time"] == "23:59"  # type: ignore[index]
    assert result["selected"]["timezone"] == "Asia/Kolkata"  # type: ignore[index]
    assert result["selected"]["timing"] == "before_cutoff"  # type: ignore[index]
