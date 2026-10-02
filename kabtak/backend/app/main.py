"""FastAPI application entry point."""

from fastapi import FastAPI

from app.routes import api_router


def create_app() -> FastAPI:
    application = FastAPI(
        title="Kabtak API",
        version="0.1.0",
        description="Deadline and evidence checking API.",
    )
    application.include_router(api_router, prefix="/v1")
    return application


app = create_app()
