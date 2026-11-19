"""模型基类与公共类型。"""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# PG 上为 JSONB，其余（sqlite 测试）退化为通用 JSON
JSONType = sa.JSON().with_variant(JSONB(), "postgresql")

# 自增主键：PG 用 BIGINT 序列，sqlite 退化为 INTEGER（autoincrement 要求）
PKType = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONType, list: JSONType}


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
