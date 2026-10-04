"""API health contract tests."""

from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_session
from app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health_reflects_configured_capabilities(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'health.db'}")
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Iterator[Session]:
        with test_session() as session:
            yield session

    settings = Settings(
        _env_file=None,
        internal_api_token="health-token",
        serpapi_api_key="test",
        llm_provider="groq",
        llm_model="test-model",
        llm_api_key="test",
    )
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Internal-Token": settings.internal_api_token},
        ) as client:
            response = await client.get("/v1/health")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database_ready"] is True
    assert payload["live_search_enabled"] is settings.live_search_enabled
    assert payload["live_extraction_enabled"] is settings.live_extraction_enabled
    assert payload["replay_enabled"] is True


@pytest.mark.anyio
async def test_health_is_degraded_before_database_migration(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'unmigrated.db'}")
    test_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Iterator[Session]:
        with test_session() as session:
            yield session

    settings = Settings(_env_file=None, internal_api_token="health-token")
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Internal-Token": settings.internal_api_token},
        ) as client:
            response = await client.get("/v1/health")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database_ready"] is False


@pytest.mark.anyio
async def test_health_rejects_direct_unauthenticated_requests() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/v1/health")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
