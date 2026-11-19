"""迁移与模型一致性：表集合必须完全一致（防止模型/迁移漂移）。"""
from __future__ import annotations


def test_migration_matches_models(client):
    from sqlalchemy import inspect

    from utp_control.db import get_engine
    from utp_control.models import Base

    insp = inspect(get_engine())
    migrated = set(insp.get_table_names()) - {"alembic_version"}
    modeled = set(Base.metadata.tables.keys())
    assert migrated == modeled, (
        f"migration/model drift: only-in-migration={migrated - modeled}, "
        f"only-in-models={modeled - migrated}"
    )
