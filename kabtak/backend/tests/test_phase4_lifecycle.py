"""Phase 4 saved-check, refresh, retry, comparison, and replay tests."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.base import Base
from app.db.models import Check, Document, Extraction, Report, Run
from app.db.session import get_session
from app.main import app
from app.routes.runs import _decision_signature, _fact_changes
from app.services.maintenance import maintenance_sweep
from app.services.registry import seed_programmes


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def terminal_check(now: datetime, *, run_status: str = "completed") -> tuple[Check, Run]:
    check = Check(
        id=str(uuid4()),
        programme_id="nmmss",
        requested_scope_json={
            "academic_year": "2026-27",
            "application_type": "fresh",
            "applicant_group": None,
        },
        profile_json={"annual_family_income_inr": 300000},
        notice_url=None,
        saved_at=None,
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    run = Run(
        id=str(uuid4()),
        check_id=check.id,
        kind="live",
        status=run_status,
        stage="finished",
        operation_scope=f"seed:{check.id}",
        idempotency_key=str(uuid4()),
        request_hash="0" * 64,
        reference_time=now,
        created_at=now,
        finished_at=now,
        error_json=(
            {"code": "RUN_FAILED", "message": "Test failure", "retryable": True}
            if run_status == "failed"
            else None
        ),
    )
    return check, run


@pytest.mark.anyio
async def test_saved_refresh_retry_and_delete_lifecycle(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'phase4.db'}")
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        internal_api_token="phase4-token",
        database_url=f"sqlite:///{tmp_path / 'phase4.db'}",
        data_dir=tmp_path / "data",
        serpapi_api_key="test",
        llm_provider="groq",
        llm_model="test-model",
        llm_api_key="test",
    )
    now = datetime.now(UTC)
    with test_sessions() as session:
        seed_programmes(session)
        refresh_check, refresh_parent = terminal_check(now)
        retry_check, failed_parent = terminal_check(now, run_status="failed")
        session.add_all([refresh_check, refresh_parent, retry_check, failed_parent])
        session.commit()

    def override_session() -> Iterator[Session]:
        with test_sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    headers = {"X-Internal-Token": settings.internal_api_token}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver", headers=headers
        ) as client:
            saved = await client.patch(f"/v1/checks/{refresh_check.id}", json={"save": True})
            saved_list = await client.get("/v1/checks?saved=true")
            first_refresh = await client.post(
                f"/v1/checks/{refresh_check.id}/refresh",
                headers={"Idempotency-Key": "refresh-key"},
            )
            duplicate_refresh = await client.post(
                f"/v1/checks/{refresh_check.id}/refresh",
                headers={"Idempotency-Key": "refresh-key"},
            )
            competing_refresh = await client.post(
                f"/v1/checks/{refresh_check.id}/refresh",
                headers={"Idempotency-Key": "another-refresh-key"},
            )
            retry = await client.post(
                f"/v1/runs/{failed_parent.id}/retry",
                headers={"Idempotency-Key": "retry-key"},
            )
            active_delete = await client.delete(f"/v1/checks/{refresh_check.id}")

        assert saved.status_code == 200
        assert saved.json()["saved_at"] is not None
        assert saved.json()["expires_at"] is None
        assert [item["id"] for item in saved_list.json()] == [refresh_check.id]
        assert first_refresh.status_code == 202
        assert duplicate_refresh.status_code == 200
        assert first_refresh.json()["run_id"] == duplicate_refresh.json()["run_id"]
        assert competing_refresh.status_code == 409
        assert competing_refresh.json()["error"]["code"] == "RUN_ACTIVE"
        assert retry.status_code == 202
        assert active_delete.status_code == 409
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.anyio
async def test_offline_replay_has_evidence_and_can_be_deleted(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'replay.db'}")
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        internal_api_token="replay-token",
        database_url=f"sqlite:///{tmp_path / 'replay.db'}",
        data_dir=tmp_path / "data",
    )
    with test_sessions() as session:
        seed_programmes(session)

    def override_session() -> Iterator[Session]:
        with test_sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    headers = {"X-Internal-Token": settings.internal_api_token}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver", headers=headers
        ) as client:
            catalogue_before = await client.get("/v1/programmes")
            examples = await client.get("/v1/examples")
            replay = await client.post(
                "/v1/examples/nmmss-2025-extension/replay",
                headers={"Idempotency-Key": "replay-key"},
            )
            duplicate = await client.post(
                "/v1/examples/nmmss-2025-extension/replay",
                headers={"Idempotency-Key": "replay-key"},
            )
            payload = replay.json()
            report = await client.get(f"/v1/runs/{payload['run_id']}/report")
            catalogue_after = await client.get("/v1/programmes")
            report_json = report.json()
            reference = report_json["student_deadline"]["evidence_refs"][0]
            evidence = await client.get(
                f"/v1/runs/{payload['run_id']}/evidence/"
                f"{reference['version_id']}/{reference['block_id']}"
            )
            replay_refresh = await client.post(
                f"/v1/checks/{payload['check_id']}/refresh",
                headers={"Idempotency-Key": "invalid-replay-refresh"},
            )
            deleted = await client.delete(f"/v1/checks/{payload['check_id']}")

        assert examples.status_code == 200 and len(examples.json()) >= 1
        assert (
            next(item for item in catalogue_before.json() if item["id"] == "nmmss")[
                "last_checked_at"
            ]
            is None
        )
        assert (
            next(item for item in catalogue_after.json() if item["id"] == "nmmss")[
                "last_checked_at"
            ]
            is not None
        )
        assert replay.status_code == 202
        assert duplicate.status_code == 200
        assert duplicate.json()["run_id"] == payload["run_id"]
        assert report.status_code == 200
        assert report_json["mode"] == "replay"
        assert "Historical replay" in " ".join(report_json["limitations"])
        assert "current deterministic rules" in " ".join(report_json["limitations"])
        assert evidence.status_code == 200
        assert "Student submission" in evidence.json()["text"]
        assert replay_refresh.status_code == 409
        assert deleted.status_code == 204
        with test_sessions() as session:
            assert session.get(Check, payload["check_id"]) is None
            assert session.get(Run, payload["run_id"]) is None
            assert session.scalar(select(func.count()).select_from(Document)) == 1
            extraction = session.scalar(select(Extraction))
            assert extraction is not None
            assert extraction.facts_json["records"]
            assert extraction.validation_json["expected_report_match"] is True
        maintenance_sweep(session_factory=test_sessions, data_dir=tmp_path / "data")
        with test_sessions() as session:
            assert session.scalar(select(func.count()).select_from(Document)) == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.anyio
async def test_run_comparison_separates_software_change(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'changes.db'}")
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(_env_file=None, internal_api_token="changes-token")
    now = datetime.now(UTC)
    with test_sessions() as session:
        seed_programmes(session)
        check, first = terminal_check(now - timedelta(hours=1))
        second = Run(
            id=str(uuid4()),
            check_id=check.id,
            kind="refresh",
            status="completed",
            stage="finished",
            operation_scope=f"comparison:{check.id}",
            idempotency_key="comparison",
            request_hash="1" * 64,
            reference_time=now,
            created_at=now,
            finished_at=now,
            version_manifest_json={"rules": "phase4"},
        )
        first.version_manifest_json = {"rules": "phase3"}
        session.add_all([check, first, second])
        session.flush()
        base_report = {
            "deadline_resolution": "supported",
            "student_deadline": {"date": "2026-10-31"},
            "eligibility": "not_assessed",
        }
        changed_report = {**base_report, "student_deadline": {"date": "2026-11-10"}}
        session.add_all(
            [
                Report(
                    id=str(uuid4()),
                    run_id=first.id,
                    report_schema_version="3",
                    decisions_json=base_report,
                    created_at=first.created_at,
                ),
                Report(
                    id=str(uuid4()),
                    run_id=second.id,
                    report_schema_version="3",
                    decisions_json=changed_report,
                    created_at=second.created_at,
                ),
            ]
        )
        session.commit()

    def override_session() -> Iterator[Session]:
        with test_sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Internal-Token": settings.internal_api_token},
        ) as client:
            response = await client.get(f"/v1/runs/{second.id}/changes")
        assert response.status_code == 200
        assert response.json()["classification"] == "software_interpretation_change"
        assert response.json()["software_versions_changed"] is True
        assert response.json()["profile_changed"] is False
        assert response.json()["changes"][0]["kind"] == "changed"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_maintenance_expires_queue_and_unsaved_terminal_checks(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'maintenance.db'}")
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with test_sessions() as session:
        seed_programmes(session)
        expired_check, expired_run = terminal_check(now - timedelta(days=2))
        expired_check.expires_at = now - timedelta(days=1)
        saved_check, saved_run = terminal_check(now - timedelta(days=2))
        saved_check.saved_at = now - timedelta(days=2)
        saved_check.expires_at = None
        queued_check, queued_run = terminal_check(now - timedelta(hours=1))
        queued_run.status = "queued"
        queued_run.stage = "queued"
        queued_run.finished_at = None
        session.add_all(
            [expired_check, expired_run, saved_check, saved_run, queued_check, queued_run]
        )
        session.commit()

    maintenance_sweep(session_factory=test_sessions, now=now, data_dir=tmp_path / "data")

    with test_sessions() as session:
        assert session.get(Check, expired_check.id) is None
        assert session.get(Check, saved_check.id) is not None
        assert session.get(Run, queued_run.id).status == "failed"  # type: ignore[union-attr]
        assert session.get(Run, queued_run.id).error_json["code"] == "QUEUE_EXPIRED"  # type: ignore[union-attr,index]
    engine.dispose()


def test_comparison_ignores_evidence_version_ids_when_facts_are_stable() -> None:
    base = {
        "scope": {
            "programme_id": "nmmss",
            "academic_year": "2026-27",
            "application_type": "fresh",
            "applicant_group": None,
        },
        "deadline_resolution": "supported",
        "student_deadline": {
            "actor": "student",
            "action": "submit",
            "date": "2026-10-31",
            "evidence_refs": [{"version_id": "version-old", "block_id": "block_1"}],
        },
        "portal_status": "not_checked",
        "eligibility": "not_assessed",
    }
    refreshed = {
        **base,
        "student_deadline": {
            **base["student_deadline"],
            "evidence_refs": [{"version_id": "version-new", "block_id": "block_1"}],
        },
    }

    assert _decision_signature(base) == _decision_signature(refreshed)
    assert _fact_changes(base, refreshed) == []

    changed = {
        **refreshed,
        "student_deadline": {**refreshed["student_deadline"], "date": "2026-11-05"},
    }
    differences = _fact_changes(base, changed)
    assert len(differences) == 1
    assert differences[0].kind == "changed"
    assert differences[0].before_evidence[0].version_id == "version-old"
    assert differences[0].after_evidence[0].version_id == "version-new"
