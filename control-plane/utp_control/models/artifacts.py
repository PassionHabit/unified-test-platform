"""日志与产物域。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin


class Artifact(Base, CreatedAtMixin):
    __tablename__ = "artifacts"
    __table_args__ = (sa.Index("ix_artifacts_execution", "execution_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(sa.ForeignKey("executions.id"), nullable=False)
    attempt_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("execution_attempts.id"), nullable=True
    )
    path: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    storage_uri: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(sa.String(64), nullable=True)
    size: Mapped[Optional[int]] = mapped_column(nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)


class LogManifest(Base):
    """日志分片清单（Agent 增量上传状态，V2.1 §12）。"""

    __tablename__ = "log_manifests"

    attempt_id: Mapped[int] = mapped_column(
        sa.ForeignKey("execution_attempts.id"), primary_key=True
    )
    stream: Mapped[str] = mapped_column(sa.String(10), default="stdout", nullable=False)
    chunk_count: Mapped[int] = mapped_column(default=0, nullable=False)
    bytes_uploaded: Mapped[int] = mapped_column(default=0, nullable=False)
    finalized: Mapped[bool] = mapped_column(default=False, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
