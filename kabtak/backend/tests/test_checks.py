"""Persisted check admission and idempotency tests."""

from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
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

    app.dependency_overrides[get_session] = override_session
    settings = get_settings()
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
