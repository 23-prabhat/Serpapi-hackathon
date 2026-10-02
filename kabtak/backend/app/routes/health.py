"""Readiness route for the frontend and local operator."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    live_search_enabled: bool
    live_extraction_enabled: bool
    replay_enabled: bool


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        live_search_enabled=settings.live_search_enabled,
        live_extraction_enabled=settings.live_extraction_enabled,
        replay_enabled=True,
    )
