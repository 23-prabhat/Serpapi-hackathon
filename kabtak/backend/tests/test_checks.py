"""Persisted check admission and idempotency tests."""

from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.services.registry import seed_programmes


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_create_check_is_persisted_and_idempotent(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    with test_session() as session:
        seed_programmes(session)

    def override_session() -> Iterator[Session]:
        with test_session() as session:
            yield session

    settings = Settings(
        _env_file=None,
        internal_api_token="idempotency-token",
        serpapi_api_key="test",
        llm_provider="groq",
        llm_model="test-model",
        llm_api_key="test",
    )
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    request = {
        "programme_id": "nmmss",
        "academic_year": "2026-27",
        "application_type": "fresh",
        "notice_url": None,
        "profile": None,
        "save": False,
    }
    headers = {
        "X-Internal-Token": settings.internal_api_token,
        "Idempotency-Key": "phase1-test-key",
    }
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
        ) as client:
            first = await client.post("/v1/checks", json=request)
            second = await client.post("/v1/checks", json=request)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["run_id"] == second.json()["run_id"]


@pytest.mark.anyio
async def test_admission_capacity_and_idempotency_are_checked_in_write_transaction(
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'capacity.db'}")
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    with test_session() as session:
        seed_programmes(session)

    def override_session() -> Iterator[Session]:
        with test_session() as session:
            yield session

    enabled = Settings(
        _env_file=None,
        internal_api_token="capacity-token",
        serpapi_api_key="test",
        llm_provider="groq",
        llm_model="test-model",
        llm_api_key="test",
        max_waiting_runs=1,
    )
    disabled = Settings(_env_file=None, internal_api_token="capacity-token", max_waiting_runs=1)
    request = {
        "programme_id": "nmmss",
        "academic_year": "2026-27",
        "application_type": "fresh",
        "notice_url": None,
        "profile": None,
        "save": False,
    }
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: enabled
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Internal-Token": "capacity-token"},
        ) as client:
            first = await client.post(
                "/v1/checks",
                json=request,
                headers={"Idempotency-Key": "capacity-first"},
            )
            app.dependency_overrides[get_settings] = lambda: disabled
            duplicate = await client.post(
                "/v1/checks",
                json=request,
                headers={"Idempotency-Key": "capacity-first"},
            )
            app.dependency_overrides[get_settings] = lambda: enabled
            full = await client.post(
                "/v1/checks",
                json=request,
                headers={"Idempotency-Key": "capacity-second"},
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert first.status_code == 202
    assert duplicate.status_code == 200
    assert duplicate.json()["run_id"] == first.json()["run_id"]
    assert full.status_code == 429
    assert full.json()["error"]["code"] == "QUEUE_FULL"
