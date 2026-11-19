"""基础设施域：节点 / 资源预留 / 自助注册令牌。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin


class WorkerNode(Base, CreatedAtMixin):
    __tablename__ = "worker_nodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(sa.String(100), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(sa.String(10), default="docker", nullable=False)
    labels: Mapped[list] = mapped_column(default=list, nullable=False)
    cpu_total: Mapped[int] = mapped_column(default=0, nullable=False)
    memory_total: Mapped[int] = mapped_column(default=0, nullable=False)
    cpu_reserved: Mapped[int] = mapped_column(default=0, nullable=False)
    memory_reserved: Mapped[int] = mapped_column(default=0, nullable=False)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    # ACTIVE / DRAINING / OFFLINE
    maintenance_state: Mapped[str] = mapped_column(sa.String(20), default="ACTIVE", nullable=False)
    maintenance_deadline: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    version: Mapped[Optional[str]] = mapped_column(sa.String(20), nullable=True)


class ResourceReservation(Base, CreatedAtMixin):
    __tablename__ = "resource_reservations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(sa.ForeignKey("execution_attempts.id"), nullable=False)
    node_id: Mapped[int] = mapped_column(sa.ForeignKey("worker_nodes.id"), nullable=False)
    cpu: Mapped[float] = mapped_column(nullable=False)
    memory_mb: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(sa.String(20), default="active", nullable=False)
    released_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class NodeEnrollmentToken(Base, CreatedAtMixin):
    """自建执行机一次性注册令牌（V2.1）。"""

    __tablename__ = "node_enrollment_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    department_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("departments.id"), nullable=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    used_by_node_id: Mapped[Optional[int]] = mapped_column(nullable=True)
