"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from app.db.session import SessionLocal
from app.errors import APIError, api_error_handler
from app.routes import api_router
from app.services.registry import seed_programmes


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    try:
        with SessionLocal() as session:
            seed_programmes(session)
    except OperationalError:
        logging.getLogger(__name__).warning(
            "Database is not migrated; run 'uv run alembic upgrade head'."
        )
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Kabtak API",
        version="0.1.0",
        description="Deadline and evidence checking API.",
        lifespan=lifespan,
    )
    application.add_exception_handler(APIError, api_error_handler)
    application.include_router(api_router, prefix="/v1")
    return application


app = create_app()
