"""M0 初始 schema：V2.1 §5 全量数据模型

Revision ID: 0001
Revises:
Create Date: 2026-11-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSONVar = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("max_concurrent", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("last_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "projects",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("department_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(10), nullable=False),
        sa.Column("repository_ref", sa.String(500), nullable=False),
        sa.Column("owner", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
    )
    op.create_table(
        "execution_profiles",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, server_default="default"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("runtime_image_ref", sa.String(500), nullable=False),
        sa.Column("prepare_spec", JSONVar, nullable=True),
        sa.Column("command_template", JSONVar, nullable=False),
        sa.Column("parameter_schema", JSONVar, nullable=False),
        sa.Column("resource_spec", JSONVar, nullable=False),
        sa.Column("artifact_spec", JSONVar, nullable=False),
        sa.Column("service_bindings", JSONVar, nullable=True),
        sa.Column("timeout_default", sa.Integer(), nullable=False, server_default="172800"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.UniqueConstraint("project_id", "name", name="uq_profile_project_name"),
    )
    op.create_table(
        "worker_nodes",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.String(100), nullable=False, unique=True),
        sa.Column("type", sa.String(10), nullable=False, server_default="docker"),
        sa.Column("labels", JSONVar, nullable=False),
        sa.Column("cpu_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memory_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cpu_reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memory_reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("maintenance_state", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("maintenance_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "node_enrollment_tokens",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_node_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
    )
    op.create_table(
        "executions",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_name", sa.String(100), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=True),
        sa.Column("caller_scope", sa.String(200), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("source_revision", sa.String(200), nullable=False),
        sa.Column("snapshot_id", sa.String(100), nullable=True),
        sa.Column("context_json", JSONVar, nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="172800"),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column("outcome", sa.String(20), nullable=False, server_default="UNKNOWN"),
        sa.Column("failure_reason", sa.String(40), nullable=False, server_default="NONE"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pipeline_run_ref", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.UniqueConstraint("caller_scope", "request_id", name="uq_execution_idempotency"),
    )
    op.create_index("ix_executions_project_created", "executions", ["project_id", "created_at"])
    op.create_index("ix_executions_status_created", "executions", ["status", "created_at"])
    op.create_table(
        "execution_attempts",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column("image_digest", sa.String(100), nullable=True),
        sa.Column("runtime_id", sa.String(200), nullable=True),
        sa.Column("spec_json", JSONVar, nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="CREATED"),
        sa.Column("start_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.String(40), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["worker_nodes.id"]),
        sa.UniqueConstraint("execution_id", "attempt_no", name="uq_attempt_no"),
    )
    op.create_table(
        "resource_reservations",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("attempt_id", sa.BigInteger(), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("cpu", sa.Float(), nullable=False),
        sa.Column("memory_mb", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["attempt_id"], ["execution_attempts.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["worker_nodes.id"]),
    )
    op.create_table(
        "execution_events",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", JSONVar, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
    )
    op.create_index("ix_events_execution_created", "execution_events", ["execution_id", "created_at"])
    op.create_table(
        "callback_delivery",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("target_ref", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
    )
    op.create_table(
        "execution_results",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=True),
        sa.Column("report_type", sa.String(30), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("failures_json", JSONVar, nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=True),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("storage_uri", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("content_type", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.ForeignKeyConstraint(["attempt_id"], ["execution_attempts.id"]),
    )
    op.create_index("ix_artifacts_execution", "artifacts", ["execution_id"])
    op.create_table(
        "log_manifests",
        sa.Column("attempt_id", sa.BigInteger(), primary_key=True),
        sa.Column("stream", sa.String(10), nullable=False, server_default="stdout"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes_uploaded", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("finalized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["attempt_id"], ["execution_attempts.id"]),
    )
    op.create_table(
        "service_catalog",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False, server_default="custom"),
        sa.Column("mode", sa.String(20), nullable=False, server_default="async_poll"),
        sa.Column("endpoint_ref", sa.String(500), nullable=False),
        sa.Column("auth_ref", sa.String(100), nullable=True),
        sa.Column("phases", JSONVar, nullable=False),
        sa.Column("params_schema", JSONVar, nullable=False),
        sa.Column("cleanup_ref", sa.String(500), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "service_invocations",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("service_ref", sa.String(100), nullable=False),
        sa.Column("phase", sa.String(10), nullable=False),
        sa.Column("external_task_id", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("request_ref", sa.String(500), nullable=True),
        sa.Column("response_ref", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
    )
    op.create_table(
        "runtime_images",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("tag", sa.String(100), nullable=False, server_default="latest"),
        sa.Column("digest", sa.String(100), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="reference"),
        sa.Column("ref_uri", sa.String(500), nullable=False),
        sa.Column("dockerfile_ref", sa.String(500), nullable=True),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("owner", sa.String(100), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="department"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
    )


def downgrade() -> None:
    for table in (
        "runtime_images",
        "service_invocations",
        "service_catalog",
        "log_manifests",
        "artifacts",
        "execution_results",
        "callback_delivery",
        "execution_events",
        "resource_reservations",
        "execution_attempts",
        "executions",
        "node_enrollment_tokens",
        "worker_nodes",
        "execution_profiles",
        "projects",
        "departments",
    ):
        op.drop_table(table)
