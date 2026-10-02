"""HTTP route registration."""

from fastapi import APIRouter

from app.routes import checks, examples, health, programmes, runs

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(programmes.router, prefix="/programmes", tags=["programmes"])
api_router.include_router(checks.router, prefix="/checks", tags=["checks"])
api_router.include_router(runs.router, prefix="/runs", tags=["runs"])
api_router.include_router(examples.router, prefix="/examples", tags=["examples"])

__all__ = ["api_router"]
