"""API health contract tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health_reflects_configured_capabilities() -> None:
    settings = get_settings()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-Internal-Token": settings.internal_api_token},
    ) as client:
        response = await client.get("/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database_ready"] is True
    assert payload["live_search_enabled"] is settings.live_search_enabled
    assert payload["live_extraction_enabled"] is settings.live_extraction_enabled
    assert payload["replay_enabled"] is True


@pytest.mark.anyio
async def test_health_rejects_direct_unauthenticated_requests() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/v1/health")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
