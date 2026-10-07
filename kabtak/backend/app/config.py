"""Environment-backed configuration shared by the API and worker."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

KABTAK_ROOT = Path(__file__).resolve().parents[2]
LEGACY_BACKEND_ENV = KABTAK_ROOT / "backend" / ".env"
SHARED_ENV = KABTAK_ROOT / ".env"


class Settings(BaseSettings):
    """Validated application settings with safe local defaults."""

    model_config = SettingsConfigDict(
        # Keep the service-local file as a migration fallback. The shared file is
        # listed last so it is the authoritative source when both exist.
        env_file=(LEGACY_BACKEND_ENV, SHARED_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    app_origin: str = "http://127.0.0.1:3000"
    internal_api_token: str = "development-only-token"

    database_url: str = "sqlite:///../data/kabtak.db"
    data_dir: Path = Path("../data")

    serpapi_api_key: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None

    active_run_timeout_seconds: int = Field(default=180, ge=1)
    source_request_timeout_seconds: int = Field(default=15, ge=1)
    source_parse_timeout_seconds: int = Field(default=10, ge=1)
    max_pdf_pages: int = Field(default=20, ge=1)
    ocr_enabled: bool = True
    ocr_timeout_seconds: int = Field(default=25, ge=1)
    max_ocr_pages: int = Field(default=10, ge=1)
    max_waiting_runs: int = Field(default=3, ge=0)
    max_search_attempts: int = Field(default=4, ge=1)
    max_source_documents: int = Field(default=6, ge=1)
    max_source_requests: int = Field(default=12, ge=1)
    max_llm_attempts: int = Field(default=6, ge=1)

    @property
    def live_search_enabled(self) -> bool:
        return bool(self.serpapi_api_key)

    @property
    def live_extraction_enabled(self) -> bool:
        return bool(self.llm_provider and self.llm_model and self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
