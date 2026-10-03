"""Supported-programme catalogue routes."""

from fastapi import APIRouter

from app.schemas.programmes import ProgrammeRead
from app.services.registry import public_programmes

router = APIRouter()


@router.get("", response_model=list[ProgrammeRead])
async def list_programmes() -> list[ProgrammeRead]:
    return [ProgrammeRead.model_validate(item) for item in public_programmes()]
