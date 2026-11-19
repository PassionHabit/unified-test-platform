"""对账器（M2，V2.1 §7/§9）。

周期比对数据库与节点心跳真实状态：
1. 活跃执行所在节点心跳超时 → RECONCILING（不重复启动）
2. RECONCILING 且节点心跳恢复 + attempt 仍活 → 回 RUNNING
3. RECONCILING 且 attempt 死线已过 + 超过收敛窗口 → 自动 LOST/FAILED(NODE_LOST)
4. DRAINING 节点排水期限已到 → 对其活跃执行发起强制取消

终态不回退；迟到/重复事件由状态机幂等吸收。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .execution_service import release_reservation
from .models import Execution, ExecutionAttempt, WorkerNode
from utp_shared.states import (
    AttemptStatus,
    ExecutionStatus,
    FailureReason,
    assert_attempt_transition,
    assert_execution_transition,
    is_attempt_terminal,
)

LIVE_ATTEMPT_STATUSES = [AttemptStatus.CREATED.value, AttemptStatus.STARTING.value, AttemptStatus.RUNNING.value]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_naive_aware(dt):
    """SQLite 可能返回 naive datetime；统一补 UTC。"""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def reconcile(db: Session) -> dict:
    """执行一轮对账，返回变更计数（幂等，可周期调用）。"""
    s = get_settings()
    now = _utcnow()
    stale_cutoff = now - timedelta(seconds=s.heartbeat_stale_s)
    lost_cutoff = now - timedelta(seconds=s.lost_grace_s)
    changed = {"reconciling": 0, "recovered": 0, "auto_lost": 0, "drain_cancelled": 0}

    rows = db.execute(
        select(Execution, ExecutionAttempt, WorkerNode)
        .join(ExecutionAttempt, ExecutionAttempt.execution_id == Execution.id)
        .join(WorkerNode, ExecutionAttempt.node_id == WorkerNode.id)
        .where(
            Execution.status.in_(
                [
                    ExecutionStatus.PREPARING.value,
                    ExecutionStatus.STARTING.value,
                    ExecutionStatus.RUNNING.value,
                    ExecutionStatus.RECONCILING.value,
                ]
            ),
            ExecutionAttempt.status.in_(LIVE_ATTEMPT_STATUSES),
        )
    ).all()

    for execution, attempt, node in rows:
        heartbeat = _to_naive_aware(node.heartbeat_at)
        deadline = _to_naive_aware(attempt.deadline_at)
        node_alive = heartbeat is not None and heartbeat >= stale_cutoff

        # 1) 心跳超时 → RECONCILING
        if not node_alive and execution.status != ExecutionStatus.RECONCILING.value:
            assert_execution_transition(execution.status, ExecutionStatus.RECONCILING.value)
            execution.status = ExecutionStatus.RECONCILING.value
            changed["reconciling"] += 1

        # 2) 心跳恢复 + 执行仍 RECONCILING → RUNNING
        elif node_alive and execution.status == ExecutionStatus.RECONCILING.value:
            assert_execution_transition(execution.status, ExecutionStatus.RUNNING.value)
            execution.status = ExecutionStatus.RUNNING.value
            changed["recovered"] += 1

        # 3) 死线已过 + 收敛窗口已过 → 自动 LOST（agent 看门狗正常时不会走到这）
        if (
            not node_alive
            and execution.status == ExecutionStatus.RECONCILING.value
            and deadline is not None
            and deadline < now
            and deadline < lost_cutoff
        ):
            assert_attempt_transition(attempt.status, AttemptStatus.LOST.value)
            attempt.status = AttemptStatus.LOST.value
            attempt.failure_reason = FailureReason.NODE_LOST.value
            attempt.ended_at = now
            release_reservation(db, attempt)
            assert_execution_transition(execution.status, ExecutionStatus.FAILED.value)
            execution.status = ExecutionStatus.FAILED.value
            execution.failure_reason = FailureReason.NODE_LOST.value
            execution.ended_at = now
            changed["auto_lost"] += 1

    # 4) DRAINING 超期 → 强制取消其活跃执行
    draining_nodes = db.execute(
        select(WorkerNode).where(WorkerNode.maintenance_state == "DRAINING")
    ).scalars().all()
    for node in draining_nodes:
        deadline = _to_naive_aware(node.maintenance_deadline)
        if deadline is None or deadline > now:
            continue
        live = db.execute(
            select(Execution, ExecutionAttempt)
            .join(ExecutionAttempt, ExecutionAttempt.execution_id == Execution.id)
            .where(
                ExecutionAttempt.node_id == node.id,
                ExecutionAttempt.status.in_(LIVE_ATTEMPT_STATUSES),
                Execution.status.in_(
                    [ExecutionStatus.PREPARING.value, ExecutionStatus.STARTING.value,
                     ExecutionStatus.RUNNING.value, ExecutionStatus.RECONCILING.value]
                ),
            )
        ).all()
        for execution, attempt in live:
            if execution.status != ExecutionStatus.CANCELLING.value:
                assert_execution_transition(execution.status, ExecutionStatus.CANCELLING.value)
                execution.status = ExecutionStatus.CANCELLING.value
            # 节点多半不在线（排水超期），直接收敛 attempt 并释放预留
            if not is_attempt_terminal(attempt.status):
                target = AttemptStatus.CANCELLED.value
                if attempt.status != target:
                    assert_attempt_transition(attempt.status, target)
                    attempt.status = target
                    attempt.ended_at = now
            release_reservation(db, attempt)
            assert_execution_transition(execution.status, ExecutionStatus.CANCELLED.value)
            execution.status = ExecutionStatus.CANCELLED.value
            execution.failure_reason = FailureReason.CANCELLED_BY_USER.value
            execution.ended_at = now
            changed["drain_cancelled"] += 1

    if any(changed.values()):
        db.commit()
    return changed


def mark_execution_lost(db: Session, execution_id: int) -> dict:
    """管理端确认丢失：attempt LOST + 执行 FAILED(NODE_LOST)。仅非终态可用。"""
    execution = db.get(Execution, execution_id)
    if execution is None:
        return {"ok": False, "reason": "not found"}
    from utp_shared.states import is_execution_terminal

    if is_execution_terminal(execution.status):
        return {"ok": False, "reason": f"already terminal: {execution.status}"}
    attempts: List[ExecutionAttempt] = db.execute(
        select(ExecutionAttempt).where(ExecutionAttempt.execution_id == execution_id)
    ).scalars().all()
    now = _utcnow()
    for attempt in attempts:
        if not is_attempt_terminal(attempt.status):
            assert_attempt_transition(attempt.status, AttemptStatus.LOST.value)
            attempt.status = AttemptStatus.LOST.value
            attempt.failure_reason = FailureReason.NODE_LOST.value
            attempt.ended_at = now
            release_reservation(db, attempt)  # 确认丢失必须释放资源预留
    execution.status = ExecutionStatus.FAILED.value
    execution.failure_reason = FailureReason.NODE_LOST.value
    execution.ended_at = now
    db.commit()
    return {"ok": True, "status": execution.status}


def mark_node_lost(db: Session, node_id: int) -> dict:
    """节点确认丢失：OFFLINE + 其上活跃执行全部走 LOST 路径。"""
    node = db.get(WorkerNode, node_id)
    if node is None:
        return {"ok": False, "reason": "not found"}
    node.maintenance_state = "OFFLINE"
    live = db.execute(
        select(Execution).join(
            ExecutionAttempt, ExecutionAttempt.execution_id == Execution.id
        ).where(
            ExecutionAttempt.node_id == node_id,
            ExecutionAttempt.status.in_(LIVE_ATTEMPT_STATUSES),
        )
    ).scalars().unique().all()
    for execution in live:
        mark_execution_lost(db, execution.id)
    return {"ok": True, "offline_executions": len(live)}
