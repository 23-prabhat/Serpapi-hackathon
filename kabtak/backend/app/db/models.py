"""Persisted Phase 1 entities shared by the API and worker."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Programme(Base):
    __tablename__ = "programmes"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    provider: Mapped[str] = mapped_column(String(300))
    registry_version: Mapped[str] = mapped_column(String(40))
    support_status: Mapped[str] = mapped_column(String(40), index=True)

    checks: Mapped[list[Check]] = relationship(back_populates="programme")


class Check(Base):
    __tablename__ = "checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    programme_id: Mapped[str] = mapped_column(ForeignKey("programmes.id"), index=True)
    requested_scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    notice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    programme: Mapped[Programme] = relationship(back_populates="checks")
    runs: Mapped[list[Run]] = relationship(
        back_populates="check", cascade="all, delete-orphan", order_by="Run.created_at"
    )


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("operation_scope", "idempotency_key", name="uq_run_idempotency"),
        Index("ix_runs_status_created_at", "status", "created_at"),
        Index(
            "uq_runs_one_active_per_check",
            "check_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    check_id: Mapped[str] = mapped_column(ForeignKey("checks.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="live")
    status: Mapped[str] = mapped_column(String(20), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    operation_scope: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    reference_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    owner_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_of_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    version_manifest_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    check: Mapped[Check] = relationship(back_populates="runs")
    report: Mapped[Report | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )
    search_requests: Mapped[list[SearchRequest]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    run_documents: Mapped[list[RunDocument]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class SearchRequest(Base):
    __tablename__ = "search_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_search_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    response_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str] = mapped_column(String(40))
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    run: Mapped[Run] = relationship(back_populates="search_requests")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    source_policy_id: Mapped[str] = mapped_column(String(100))
    publisher_role: Mapped[str] = mapped_column(String(60))

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "sha256", "parser_version", name="uq_document_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    sha256: Mapped[str] = mapped_column(String(64))
    original_path: Mapped[str] = mapped_column(Text)
    parsed_blocks_path: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(40))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parse_status: Mapped[str] = mapped_column(String(40))

    document: Mapped[Document] = relationship(back_populates="versions")
    extractions: Mapped[list[Extraction]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )


class Extraction(Base):
    __tablename__ = "extractions"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "model_id",
            "prompt_hash",
            "schema_version",
            name="uq_extraction_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    model_id: Mapped[str] = mapped_column(String(200))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(40))
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    document_version: Mapped[DocumentVersion] = relationship(back_populates="extractions")


class RunDocument(Base):
    __tablename__ = "run_documents"
    __table_args__ = (UniqueConstraint("run_id", "requested_url", name="uq_run_document_url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    requested_url: Mapped[str] = mapped_column(Text)
    resolved_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True
    )
    extraction_id: Mapped[str | None] = mapped_column(
        ForeignKey("extractions.id", ondelete="SET NULL"), nullable=True
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cache_provenance: Mapped[str] = mapped_column(String(40))
    fetch_status: Mapped[str] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    run: Mapped[Run] = relationship(back_populates="run_documents")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), unique=True)
    report_schema_version: Mapped[str] = mapped_column(String(40))
    decisions_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    run: Mapped[Run] = relationship(back_populates="report")


class WorkerState(Base):
    __tablename__ = "worker_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    worker_id: Mapped[str] = mapped_column(String(100))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
