"""API scaffold smoke tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health_reports_offline_capabilities() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "live_search_enabled": False,
        "live_extraction_enabled": False,
        "replay_enabled": True,
    }
