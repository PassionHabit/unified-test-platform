"""组织与工程配置：部门 / 项目 / 执行配置 / 镜像库。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin


class Department(Base, CreatedAtMixin):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(sa.String(100), unique=True, nullable=False)
    max_concurrent: Mapped[int] = mapped_column(default=20, nullable=False)
    # 公平排队依据：最近一次被调度的时间（越旧越优先）
    last_scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class Project(Base, CreatedAtMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(sa.String(100), unique=True, nullable=False)
    department_id: Mapped[int] = mapped_column(
        sa.ForeignKey("departments.id"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(sa.String(10), nullable=False)  # git | svn
    repository_ref: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    owner: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="active", nullable=False)


class ExecutionProfile(Base, CreatedAtMixin):
    __tablename__ = "execution_profiles"
    __table_args__ = (sa.UniqueConstraint("project_id", "name", name="uq_profile_project_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(100), default="default", nullable=False)
    revision: Mapped[int] = mapped_column(default=1, nullable=False)
    runtime_image_ref: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    prepare_spec: Mapped[Optional[dict]] = mapped_column(nullable=True)  # {argv:[], timeout_s:600}
    command_template: Mapped[dict] = mapped_column(nullable=False)  # {argv:[...]}
    parameter_schema: Mapped[dict] = mapped_column(default=dict, nullable=False)
    resource_spec: Mapped[dict] = mapped_column(default=dict, nullable=False)
    artifact_spec: Mapped[dict] = mapped_column(default=dict, nullable=False)
    service_bindings: Mapped[Optional[dict]] = mapped_column(nullable=True)
    timeout_default: Mapped[int] = mapped_column(default=172800, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)


class RuntimeImage(Base, CreatedAtMixin):
    """镜像库条目：official（平台公共）/ reference（引用现成地址）/ build（Dockerfile 构建，M4）。"""

    __tablename__ = "runtime_images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    tag: Mapped[str] = mapped_column(sa.String(100), default="latest", nullable=False)
    digest: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    source: Mapped[str] = mapped_column(sa.String(20), default="reference", nullable=False)
    ref_uri: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    dockerfile_ref: Mapped[Optional[str]] = mapped_column(sa.String(500), nullable=True)
    department_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("departments.id"), nullable=True
    )
    owner: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    visibility: Mapped[str] = mapped_column(sa.String(20), default="department", nullable=False)
    status: Mapped[str] = mapped_column(sa.String(20), default="active", nullable=False)
