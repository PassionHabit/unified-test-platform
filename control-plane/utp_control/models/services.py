"""公共服务域：目录 + 调用实例（V2.1 §10，条目由管理员配置登记）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin


class ServiceCatalog(Base, CreatedAtMixin):
    __tablename__ = "service_catalog"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(sa.String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(10), default="custom", nullable=False)  # preset | custom
    mode: Mapped[str] = mapped_column(sa.String(20), default="async_poll", nullable=False)  # sync | async_poll | async_callback
    endpoint_ref: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    auth_ref: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    phases: Mapped[list] = mapped_column(default=list, nullable=False)  # ["before","during","after"]
    params_schema: Mapped[dict] = mapped_column(default=dict, nullable=False)
    cleanup_ref: Mapped[Optional[str]] = mapped_column(sa.String(500), nullable=True)
    visibility: Mapped[str] = mapped_column(sa.String(20), default="public", nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)


class ServiceInvocation(Base, CreatedAtMixin):
    __tablename__ = "service_invocations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(sa.ForeignKey("executions.id"), nullable=False)
    service_ref: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    phase: Mapped[str] = mapped_column(sa.String(10), nullable=False)  # before | during | after
    external_task_id: Mapped[Optional[str]] = mapped_column(sa.String(200), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="pending", nullable=False)
    request_ref: Mapped[Optional[str]] = mapped_column(sa.String(500), nullable=True)
    response_ref: Mapped[Optional[str]] = mapped_column(sa.String(500), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)
