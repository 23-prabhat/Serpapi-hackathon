"""Single-process SQLite worker for persisted Kabtak runs."""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import socket
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy import select, text, update

from app.config import Settings, get_settings
from app.db.models import Run, WorkerState
from app.db.session import SessionLocal
from app.services.failures import ProcessingError
from app.services.pipeline import process_run
from app.services.registry import seed_programmes

LOGGER = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


@contextmanager
def worker_lock(settings: Settings):
    lock_path = Path(settings.data_dir).resolve() / "worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle: BinaryIO = lock_path.open("a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError("Another Kabtak worker is already running") from exc
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def set_worker_heartbeat(worker_id: str) -> None:
    with SessionLocal.begin() as session:
        state = session.get(WorkerState, 1)
        if state is None:
            session.add(WorkerState(id=1, worker_id=worker_id, heartbeat_at=utcnow()))
        else:
            state.worker_id = worker_id
            state.heartbeat_at = utcnow()


def recover_stale_runs() -> None:
    cutoff = utcnow() - timedelta(seconds=60)
    with SessionLocal.begin() as session:
        session.execute(
            update(Run)
            .where(
                Run.status == "running",
                Run.heartbeat_at.is_not(None),
                Run.heartbeat_at < cutoff,
            )
            .values(
                status="interrupted",
                stage="finished",
                owner_token=None,
                finished_at=utcnow(),
                error_json={
                    "code": "WORKER_INTERRUPTED",
                    "message": "The worker stopped before this run completed.",
                    "retryable": True,
                },
            )
        )


def claim_next_run(worker_id: str) -> tuple[str, str] | None:
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        run = session.scalar(
            select(Run).where(Run.status == "queued").order_by(Run.created_at).limit(1)
        )
        if run is None:
            session.commit()
            return None
        owner_token = uuid4().hex
        now = utcnow()
        run.status = "running"
        run.stage = "searching"
        run.worker_id = worker_id
        run.owner_token = owner_token
        run.started_at = now
        run.heartbeat_at = now
        session.commit()
        return run.id, owner_token


def mark_failed(run_id: str, owner_token: str, exc: Exception) -> None:
    if isinstance(exc, ProcessingError):
        safe_code = exc.code
        public_message = exc.public_message
        retryable = exc.retryable
    else:
        safe_code = {
            "HTTPStatusError": "EXTERNAL_SERVICE_ERROR",
            "ConnectTimeout": "SOURCE_TIMEOUT",
            "ReadTimeout": "SOURCE_TIMEOUT",
        }.get(type(exc).__name__, "RUN_FAILED")
        public_message = "The live check could not be completed. Review the worker log and retry."
        retryable = True
    with SessionLocal.begin() as session:
        run = session.scalar(
            select(Run).where(
                Run.id == run_id,
                Run.owner_token == owner_token,
                Run.status == "running",
            )
        )
        if run is None:
            return
        run.status = "failed"
        run.stage = "finished"
        run.finished_at = utcnow()
        run.heartbeat_at = utcnow()
        run.error_json = {
            "code": safe_code,
            "message": public_message,
            "retryable": retryable,
        }
    LOGGER.exception("run_failed run_id=%s error_type=%s", run_id, type(exc).__name__)


class HeartbeatThread:
    def __init__(self, worker_id: str) -> None:
        self.worker_id = worker_id
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=6)

    def _run(self) -> None:
        while not self.stop_event.wait(5):
            try:
                set_worker_heartbeat(self.worker_id)
            except Exception:  # noqa: BLE001 - main worker owns failure handling.
                LOGGER.exception("worker_heartbeat_failed")


def run_worker(*, once: bool = False) -> None:
    settings = get_settings()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # SerpApi requires the key in the query string, so third-party request logs
    # must never emit full URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    with worker_lock(settings):
        with SessionLocal() as session:
            seed_programmes(session)
        recover_stale_runs()
        set_worker_heartbeat(worker_id)
        heartbeat = HeartbeatThread(worker_id)
        heartbeat.start()
        try:
            while True:
                set_worker_heartbeat(worker_id)
                claimed = claim_next_run(worker_id)
                if claimed is None:
                    if once:
                        return
                    sleep(1)
                    continue
                run_id, owner_token = claimed
                LOGGER.info("run_claimed run_id=%s", run_id)
                try:
                    process_run(run_id, owner_token, settings)
                    LOGGER.info("run_completed run_id=%s", run_id)
                except Exception as exc:  # noqa: BLE001 - terminal run state is required.
                    mark_failed(run_id, owner_token, exc)
                if once:
                    return
        finally:
            heartbeat.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process at most one queued run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        run_worker(once=args.once)
    except KeyboardInterrupt:
        LOGGER.info("worker_stopped")


if __name__ == "__main__":
    main()
