"""FastAPI application entry point."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from app.db.session import SessionLocal
from app.errors import APIError, api_error_handler
from app.routes import api_router
from app.services.maintenance import maintenance_sweep
from app.services.registry import seed_programmes


async def _maintenance_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(maintenance_sweep)
        except Exception:  # noqa: BLE001 - maintenance retries on the next interval.
            logging.getLogger(__name__).exception("maintenance_sweep_failed")
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    try:
        with SessionLocal() as session:
            seed_programmes(session)
    except OperationalError:
        logging.getLogger(__name__).warning(
            "Database is not migrated; run 'uv run alembic upgrade head'."
        )
    maintenance = asyncio.create_task(_maintenance_loop())
    try:
        yield
    finally:
        maintenance.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await maintenance


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
