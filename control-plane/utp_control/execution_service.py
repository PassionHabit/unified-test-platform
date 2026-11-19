"""执行服务：Attempt 上报 → 状态机推进 → 预留释放 → 结果解析 → 终态收尾。

所有状态变更走 shared 状态机校验；终态路径统一经过 finalize_execution。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Artifact,
    Execution,
    ExecutionAttempt,
    ExecutionEvent,
    ExecutionResult,
    ResourceReservation,
    WorkerNode,
)
from .result_parser import parse_report
from utp_shared.events import EventType
from utp_shared.states import (
    AttemptStatus,
    ExecutionStatus,
    FailureReason,
    Outcome,
    assert_attempt_transition,
    assert_execution_transition,
    is_execution_terminal,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event(db: Session, execution_id: int, event_type: str, payload: Optional[dict] = None) -> None:
    db.add(ExecutionEvent(execution_id=execution_id, event_type=event_type, payload=payload or {}))


def release_reservation(db: Session, attempt: ExecutionAttempt) -> None:
    """释放 attempt 占用的节点资源（幂等）。"""
    if attempt.node_id is None:
        return
    reservations = db.execute(
        select(ResourceReservation).where(
            ResourceReservation.attempt_id == attempt.id,
            ResourceReservation.state == "active",
        )
    ).scalars().all()
    node = db.get(WorkerNode, attempt.node_id)
    for r in reservations:
        r.state = "released"
        r.released_at = _utcnow()
        if node is not None:
            node.cpu_reserved = max(0, int(node.cpu_reserved - r.cpu))
            node.memory_reserved = max(0, int(node.memory_reserved - r.memory_mb))


def attempt_failure_reason(exit_code: Optional[int], oom_killed: bool, message: str) -> str:
    if oom_killed:
        return FailureReason.CONTAINER_OOM_KILLED.value
    if exit_code not in (None, 0):
        return FailureReason.PROCESS_EXIT_NONZERO.value
    return FailureReason.NONE.value


def parse_and_store_result(db: Session, execution: Execution, attempt: ExecutionAttempt) -> Optional[ExecutionResult]:
    """解析报告产物 → execution_result + outcome。解析失败不阻塞交付。"""
    artifacts = db.execute(
        select(Artifact).where(Artifact.execution_id == execution.id)
    ).scalars().all()

    # 报告类型来自 profile artifact_spec.report_type；无则 NOT_EVALUATED
    from .models import ExecutionProfile, Project

    profile = db.execute(
        select(ExecutionProfile).where(
            ExecutionProfile.project_id == execution.project_id,
            ExecutionProfile.name == execution.profile_name,
        )
    ).scalar_one_or_none()
    report_type = (profile.artifact_spec or {}).get("report_type") if profile else None
    if not report_type:
        execution.outcome = Outcome.NOT_EVALUATED.value
        return None

    # 解析需要读产物内容：找匹配的报告文件（junit/robot 优先按 content/path）
    from .storage import get_storage

    report_bytes = None
    for art in artifacts:
        if report_type == "pytest" and ("junit" in art.path.lower() or art.path.endswith(".xml")):
            report_bytes = _read_artifact(art)
            if report_bytes:
                break
        if report_type == "robot" and art.path.endswith("output.xml"):
            report_bytes = _read_artifact(art)
            if report_bytes:
                break

    if report_bytes is None:
        execution.outcome = Outcome.NOT_EVALUATED.value
        return None

    parsed = parse_report(report_type, report_bytes)
    if parsed is None:
        execution.outcome = Outcome.NOT_EVALUATED.value
        return None

    result = ExecutionResult(
        execution_id=execution.id,
        attempt_id=attempt.id,
        report_type=report_type,
        total=parsed["total"],
        passed=parsed["passed"],
        failed=parsed["failed"],
        skipped=parsed["skipped"],
        duration_s=parsed.get("duration_s"),
        failures_json={"cases": parsed["failures"][:200]},
    )
    db.add(result)
    execution.outcome = (
        Outcome.PASSED.value if parsed["failed"] == 0 else Outcome.FAILED.value
    )
    _event(
        db,
        execution.id,
        EventType.RESULT_SUMMARY_PARSED.value,
        {"total": parsed["total"], "failed": parsed["failed"]},
    )
    return result


def _read_artifact(art: Artifact) -> Optional[bytes]:
    try:
        from .storage import get_storage

        return get_storage().get_bytes(art.storage_uri)
    except Exception:
        return None


def finalize_execution(
    db: Session,
    execution: Execution,
    attempt: ExecutionAttempt,
    infra_failure: Optional[str] = None,
) -> None:
    """统一终态路径：FINALIZING → COMPLETED/FAILED/CANCELLED。"""
    now = _utcnow()
    if execution.status not in (
        ExecutionStatus.FINALIZING.value,
        ExecutionStatus.CANCELLING.value,
    ):
        if infra_failure and execution.status in (
            ExecutionStatus.PREPARING.value,
            ExecutionStatus.STARTING.value,
            ExecutionStatus.RECONCILING.value,
        ):
            # 尚未真正运行：直接进 FAILED（PREPARING/STARTING/RECONCILING 均可达）
            assert_execution_transition(execution.status, ExecutionStatus.FAILED.value)
            execution.status = ExecutionStatus.FAILED.value
            execution.failure_reason = infra_failure
            execution.ended_at = now
            release_reservation(db, attempt)
            _event(db, execution.id, EventType.EXECUTION_FINALIZED.value, {"status": execution.status})
            db.commit()
            return
        # RUNNING/STARTING/PREPARING → FINALIZING
        assert_execution_transition(execution.status, ExecutionStatus.FINALIZING.value)
        execution.status = ExecutionStatus.FINALIZING.value

    release_reservation(db, attempt)

    if execution.status == ExecutionStatus.CANCELLING.value:
        execution.status = ExecutionStatus.CANCELLED.value
        execution.failure_reason = FailureReason.CANCELLED_BY_USER.value
    elif infra_failure:
        execution.status = ExecutionStatus.FAILED.value
        execution.failure_reason = infra_failure
    else:
        parse_and_store_result(db, execution, attempt)
        execution.status = ExecutionStatus.COMPLETED.value

    execution.ended_at = now
    attempt.ended_at = attempt.ended_at or now
    _event(db, execution.id, EventType.EXECUTION_FINALIZED.value, {"status": execution.status})
    db.commit()

    # after 服务与 during 清理（尽力而为，不改变终态）
    try:
        from . import services_runtime
        from .models import ExecutionProfile

        profile = db.query(ExecutionProfile).filter(
            ExecutionProfile.project_id == execution.project_id,
            ExecutionProfile.name == execution.profile_name,
        ).first()
        bindings = (profile.service_bindings or {}).get("bindings", []) if profile and profile.service_bindings else []
        services_runtime.run_after_services(db, execution, bindings)
    except Exception:
        pass


def apply_attempt_report(db: Session, report) -> dict:
    """Agent 状态上报的幂等处理（迟到/重复事件容忍）。"""
    attempt = db.get(ExecutionAttempt, int(report.attempt_id))
    if attempt is None:
        return {"accepted": False, "reason": "unknown attempt"}

    execution = db.get(Execution, attempt.execution_id)
    now = _utcnow()

    target = report.status.value

    # 重复/迟到上报：目标态等于当前态或已是终态 → 记录后幂等返回
    if attempt.status == target or is_execution_terminal(execution.status):
        db.commit()
        return {"accepted": True, "idempotent": True}

    assert_attempt_transition(attempt.status, target)
    attempt.status = target

    if target == AttemptStatus.STARTING.value:
        if execution.status == ExecutionStatus.PREPARING.value:
            assert_execution_transition(execution.status, ExecutionStatus.STARTING.value)
            execution.status = ExecutionStatus.STARTING.value
            execution.started_at = execution.started_at or now

    elif target == AttemptStatus.RUNNING.value:
        if execution.status == ExecutionStatus.STARTING.value:
            assert_execution_transition(execution.status, ExecutionStatus.RUNNING.value)
            execution.status = ExecutionStatus.RUNNING.value
        elif execution.status == ExecutionStatus.RECONCILING.value:  # M2 恢复路径
            assert_execution_transition(execution.status, ExecutionStatus.RUNNING.value)
            execution.status = ExecutionStatus.RUNNING.value
        attempt.start_confirmed_at = attempt.start_confirmed_at or now

    elif target == AttemptStatus.EXITED.value:
        attempt.exit_code = report.exit_code
        attempt.failure_reason = attempt_failure_reason(
            report.exit_code, report.oom_killed, report.message or ""
        )
        finalize_execution(db, execution, attempt)

    elif target == AttemptStatus.CANCELLED.value:
        finalize_execution(db, execution, attempt)

    elif target == AttemptStatus.LOST.value:
        attempt.failure_reason = FailureReason.NODE_LOST.value
        finalize_execution(db, execution, attempt, infra_failure=FailureReason.NODE_LOST.value)

    _event(
        db,
        execution.id,
        EventType.ATTEMPT_REPORTED.value,
        {"attempt_status": target, "exit_code": report.exit_code},
    )
    db.commit()
    return {"accepted": True}
