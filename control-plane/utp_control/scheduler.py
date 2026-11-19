"""调度器：从持久化队列领取任务并构造不可变 AttemptSpec。

PG 用 FOR UPDATE SKIP LOCKED 防并发重复领取；SQLite 写事务天然串行，
同一事务内完成领取+预留，原子性等价（测试路径）。
M1：单节点标签/容量过滤；M2 在此之上加部门公平与配额。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Execution, ExecutionAttempt, ExecutionProfile, Project, WorkerNode
from utp_shared.states import ExecutionStatus, assert_execution_transition


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _candidate_labels(profile: ExecutionProfile) -> List[str]:
    return list((profile.resource_spec or {}).get("required_labels", []))


def _resource_request(profile: ExecutionProfile) -> Tuple[float, int]:
    spec = profile.resource_spec or {}
    return float(spec.get("cpu", 1)), int(spec.get("memory_mb", 1024))


def node_can_run(node: WorkerNode, profile: ExecutionProfile) -> bool:
    if node.maintenance_state != "ACTIVE":
        return False
    labels = set(node.labels or [])
    if not set(_candidate_labels(profile)).issubset(labels):
        return False
    cpu, mem = _resource_request(profile)
    return node.cpu_reserved + cpu <= node.cpu_total and node.memory_reserved + mem <= node.memory_total


def build_attempt_spec(execution: Execution, profile: ExecutionProfile, attempt_id: int) -> dict:
    """不可变 spec（V2.1 §8）；命令数组直接取自 profile，敏感值仅 env。"""
    argv = list((profile.command_template or {}).get("argv", []))
    env = dict((execution.context_json or {}).get("parameters", {}).get("environment", {}))
    resources = profile.resource_spec or {}
    deadline = _utcnow() + timedelta(seconds=execution.timeout_seconds)
    return {
        "attempt_id": str(attempt_id),
        "execution_id": str(execution.id),
        "image": profile.runtime_image_ref,
        "argv": argv,
        "env": {str(k): str(v) for k, v in env.items()},
        "resources": {
            "cpu": resources.get("cpu", 1),
            "memory_mb": resources.get("memory_mb", 1024),
            "shm_mb": resources.get("shm_mb", 1024),
        },
        "deadline_at": deadline.isoformat(),
    }


def claim_for_node(db: Session, node: WorkerNode, limit: int = 1) -> List[dict]:
    """领取最多 limit 个任务：建 Attempt、占资源、推进状态。同一事务内原子完成。"""
    if node.maintenance_state != "ACTIVE":
        return []

    stmt = (
        select(Execution, ExecutionProfile)
        .join(Project, Execution.project_id == Project.id)
        .join(
            ExecutionProfile,
            (ExecutionProfile.project_id == Project.id)
            & (ExecutionProfile.name == Execution.profile_name),
        )
        .where(Execution.status == ExecutionStatus.QUEUED.value)
        .order_by(Execution.priority.desc(), Execution.created_at.asc(), Execution.id.asc())
        .limit(50)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    rows = db.execute(stmt).all()
    specs: List[dict] = []
    for execution, profile in rows:
        if len(specs) >= limit:
            break
        if not node_can_run(node, profile):
            continue
        if not profile.enabled:
            continue

        attempt = ExecutionAttempt(
            execution_id=execution.id,
            attempt_no=1,
            node_id=node.id,
            status="CREATED",  # Agent 首个 STARTING 上报完成 CREATED→STARTING 迁移
            deadline_at=_utcnow() + timedelta(seconds=execution.timeout_seconds),
        )
        db.add(attempt)
        db.flush()  # 拿 attempt.id

        spec = build_attempt_spec(execution, profile, attempt.id)
        attempt.spec_json = spec

        cpu, mem = _resource_request(profile)
        from .models import ResourceReservation

        db.add(
            ResourceReservation(
                attempt_id=attempt.id, node_id=node.id, cpu=cpu, memory_mb=mem, state="active"
            )
        )
        node.cpu_reserved = int(node.cpu_reserved + cpu)
        node.memory_reserved = int(node.memory_reserved + mem)

        assert_execution_transition(execution.status, ExecutionStatus.PREPARING.value)
        execution.status = ExecutionStatus.PREPARING.value
        specs.append(spec)
    if specs:
        db.commit()
    return specs
