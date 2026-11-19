"""执行域：Execution / Attempt / 事件 / 回调 / 结果摘要。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin


class Execution(Base, CreatedAtMixin):
    __tablename__ = "executions"
    __table_args__ = (
        sa.UniqueConstraint("caller_scope", "request_id", name="uq_execution_idempotency"),
        sa.Index("ix_executions_project_created", "project_id", "created_at"),
        sa.Index("ix_executions_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    profile_name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    profile_revision: Mapped[Optional[int]] = mapped_column(nullable=True)
    caller_scope: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    request_id: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    priority: Mapped[int] = mapped_column(sa.SmallInteger, default=0, nullable=False)
    source_revision: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    snapshot_id: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    context_json: Mapped[dict] = mapped_column(default=dict, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(default=172800, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(20), default="QUEUED", nullable=False)
    outcome: Mapped[str] = mapped_column(sa.String(20), default="UNKNOWN", nullable=False)
    failure_reason: Mapped[str] = mapped_column(sa.String(40), default="NONE", nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    pipeline_run_ref: Mapped[Optional[str]] = mapped_column(sa.String(200), nullable=True)


class ExecutionAttempt(Base, CreatedAtMixin):
    __tablename__ = "execution_attempts"
    __table_args__ = (sa.UniqueConstraint("execution_id", "attempt_no", name="uq_attempt_no"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(sa.ForeignKey("executions.id"), nullable=False)
    attempt_no: Mapped[int] = mapped_column(default=1, nullable=False)
    node_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("worker_nodes.id"), nullable=True
    )
    image_digest: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    runtime_id: Mapped[Optional[str]] = mapped_column(sa.String(200), nullable=True)
    spec_json: Mapped[Optional[dict]] = mapped_column(nullable=True)
    deadline_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="CREATED", nullable=False)
    start_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    exit_code: Mapped[Optional[int]] = mapped_column(nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(sa.String(40), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class ExecutionEvent(Base):
    __tablename__ = "execution_events"
    __table_args__ = (sa.Index("ix_events_execution_created", "execution_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(sa.ForeignKey("executions.id"), nullable=False)
    attempt_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class CallbackDelivery(Base, CreatedAtMixin):
    __tablename__ = "callback_delivery"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(sa.ForeignKey("executions.id"), nullable=False)
    target_ref: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    state: Mapped[str] = mapped_column(sa.String(20), default="pending", nullable=False)


class ExecutionResult(Base):
    """轻量结果摘要（V2.1 §12，M3 解析器写入）。"""

    __tablename__ = "execution_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(sa.ForeignKey("executions.id"), nullable=False)
    attempt_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    report_type: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    total: Mapped[int] = mapped_column(default=0, nullable=False)
    passed: Mapped[int] = mapped_column(default=0, nullable=False)
    failed: Mapped[int] = mapped_column(default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(default=0, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(sa.String(500), nullable=True)
    duration_s: Mapped[Optional[int]] = mapped_column(nullable=True)
    failures_json: Mapped[Optional[dict]] = mapped_column(nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
