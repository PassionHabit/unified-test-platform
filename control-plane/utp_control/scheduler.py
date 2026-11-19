"""调度器（M2）：持久化队列 + 部门公平轮询 + 部门并发配额 + 资源预留。

领取事务（PG：FOR UPDATE SKIP LOCKED；SQLite：写事务天然串行）内完成：
候选排序（部门最久未调度优先 → priority 降序 → 先来先服务）→ 配额检查 →
标签/容量过滤 → 建 Attempt + 预留 + 部门时间戳推进，原子提交。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Department,
    Execution,
    ExecutionAttempt,
    ExecutionProfile,
    Project,
    ResourceReservation,
    WorkerNode,
)
from utp_shared.states import ExecutionStatus, assert_execution_transition

ACTIVE_EXECUTION_STATUSES = [
    ExecutionStatus.PREPARING.value,
    ExecutionStatus.STARTING.value,
    ExecutionStatus.RUNNING.value,
    ExecutionStatus.RECONCILING.value,
    ExecutionStatus.FINALIZING.value,
]


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
        "prepare": profile.prepare_spec,
        "resources": {
            "cpu": resources.get("cpu", 1),
            "memory_mb": resources.get("memory_mb", 1024),
            "shm_mb": resources.get("shm_mb", 1024),
        },
        "workspace_dir": "/workspace",
        "artifacts_dir": "/artifacts",
        "deadline_at": deadline.isoformat(),
    }


def _department_active_count(db: Session, department_id: int) -> int:
    return (
        db.execute(
            select(func.count(Execution.id))
            .join(Project, Execution.project_id == Project.id)
            .where(
                Project.department_id == department_id,
                Execution.status.in_(ACTIVE_EXECUTION_STATUSES),
            )
        ).scalar_one()
        or 0
    )


def claim_for_node(db: Session, node: WorkerNode, limit: int = 1) -> List[dict]:
    """领取最多 limit 个任务。部门公平 + 配额 + 过滤在同一事务内原子完成。"""
    if node.maintenance_state != "ACTIVE":
        return []

    stmt = (
        select(Execution, ExecutionProfile, Project, Department)
        .join(Project, Execution.project_id == Project.id)
        .join(
            ExecutionProfile,
            (ExecutionProfile.project_id == Project.id)
            & (ExecutionProfile.name == Execution.profile_name),
        )
        .join(Department, Project.department_id == Department.id)
        .where(Execution.status == ExecutionStatus.QUEUED.value)
        # 公平：最久未调度的部门优先（NULL 视为最旧）；同级 priority 高者优先；再按提交时间
        .order_by(
            Department.last_scheduled_at.asc().nulls_first(),
            Execution.priority.desc(),
            Execution.created_at.asc(),
            Execution.id.asc(),
        )
        .limit(200)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    rows = db.execute(stmt).all()
    specs: List[dict] = []
    now = _utcnow()
    for execution, profile, project, department in rows:
        if len(specs) >= limit:
            break
        if not profile.enabled or not node_can_run(node, profile):
            continue
        # 部门并发配额
        if _department_active_count(db, department.id) >= department.max_concurrent:
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
        db.add(
            ResourceReservation(
                attempt_id=attempt.id, node_id=node.id, cpu=cpu, memory_mb=mem, state="active"
            )
        )
        node.cpu_reserved = int(node.cpu_reserved + cpu)
        node.memory_reserved = int(node.memory_reserved + mem)

        assert_execution_transition(execution.status, ExecutionStatus.PREPARING.value)
        execution.status = ExecutionStatus.PREPARING.value

        # 部门公平指针推进
        department.last_scheduled_at = now
        specs.append(spec)
    if specs:
        db.commit()
    return specs
