"""Internal authentication for the loopback Next.js proxy."""

import secrets
from typing import Annotated

from fastapi import Depends, Header

from app.config import Settings, get_settings
from app.errors import APIError


def require_internal_token(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    if not x_internal_token or not secrets.compare_digest(
        x_internal_token, settings.internal_api_token
    ):
        raise APIError(401, "UNAUTHORIZED", "The internal API token is missing or invalid.")
