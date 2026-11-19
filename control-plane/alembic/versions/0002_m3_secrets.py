"""M3：秘密引用表（值加密存储，键来自 UTP_SECRET_KEY）

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secret_refs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("value_encrypted", sa.Text(), nullable=False),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("secret_refs")
