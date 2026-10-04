"""Critical worker-recovery regressions required by the Phase 5 gate."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import worker
from app.db.base import Base
from app.db.models import Check, Run
from app.services.registry import seed_programmes


def running_check(now: datetime, *, stale: bool) -> tuple[Check, Run]:
    check_id = str(uuid4())
    check = Check(
        id=check_id,
        programme_id="nmmss",
        requested_scope_json={
            "academic_year": "2026-27",
            "application_type": "fresh",
            "applicant_group": None,
        },
        profile_json=None,
        notice_url=None,
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    heartbeat = now - timedelta(minutes=2) if stale else now
    run = Run(
        id=str(uuid4()),
        check_id=check_id,
        kind="live",
        status="running",
        stage="fetching",
        operation_scope=f"check:{check_id}:live",
        idempotency_key=str(uuid4()),
        request_hash="0" * 64,
        reference_time=now,
        created_at=now - timedelta(minutes=3),
        started_at=now - timedelta(minutes=3),
        worker_id="worker-before-restart",
        owner_token="old-owner-token",
        heartbeat_at=heartbeat,
    )
    return check, run


def test_worker_restart_interrupts_only_stale_run_and_rejects_old_owner(
    tmp_path, monkeypatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'recovery.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with sessions() as session:
        seed_programmes(session)
        stale_check, stale_run = running_check(now, stale=True)
        fresh_check, fresh_run = running_check(now, stale=False)
        session.add_all([stale_check, stale_run, fresh_check, fresh_run])
        session.commit()

    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "utcnow", lambda: now)
    worker.recover_stale_runs()

    with sessions() as session:
        recovered = session.get(Run, stale_run.id)
        active = session.get(Run, fresh_run.id)
        assert recovered is not None
        assert recovered.status == "interrupted"
        assert recovered.stage == "finished"
        assert recovered.owner_token is None
        assert recovered.error_json == {
            "code": "WORKER_INTERRUPTED",
            "message": "The worker stopped before this run completed.",
            "retryable": True,
        }
        assert active is not None and active.status == "running"

    worker.mark_failed(stale_run.id, "old-owner-token", RuntimeError("late worker result"))
    with sessions() as session:
        recovered = session.get(Run, stale_run.id)
        assert recovered is not None
        assert recovered.status == "interrupted"
        assert recovered.error_json["code"] == "WORKER_INTERRUPTED"
    engine.dispose()
