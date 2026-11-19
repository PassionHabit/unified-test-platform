"""/api/v1/executions：提交（幂等）、查询、列表、取消。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Execution, ExecutionEvent, ExecutionProfile, Project
from ...schemas import CancelOut, CallerInfo, ExecutionCreate, ExecutionOut
from utp_shared.events import EventType
from utp_shared.states import (
    ExecutionStatus,
    FailureReason,
    assert_execution_transition,
    is_execution_terminal,
)

router = APIRouter(tags=["executions"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_404(db: Session, execution_id: int) -> Execution:
    execution = db.get(Execution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail=f"execution {execution_id} not found")
    return execution


def _add_event(db: Session, execution_id: int, event_type: str, payload: Optional[dict] = None) -> None:
    db.add(ExecutionEvent(execution_id=execution_id, event_type=event_type, payload=payload or {}))


@router.post(
    "/executions",
    response_model=ExecutionOut,
    status_code=202,
    summary="提交执行（Idempotency-Key 头实现幂等重放）",
)
def submit_execution(
    body: ExecutionCreate,
    response: Response,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> Execution:
    project = db.execute(select(Project).where(Project.name == body.project_id)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail=f"project '{body.project_id}' not found")

    profile_name = body.profile or "default"
    profile = db.execute(
        select(ExecutionProfile).where(
            ExecutionProfile.project_id == project.id,
            ExecutionProfile.name == profile_name,
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile '{profile_name}' not found")

    caller = body.caller or CallerInfo()
    caller_scope = f"{caller.type}:{caller.run_ref or 'adhoc'}"

    if idempotency_key:
        existing = db.execute(
            select(Execution).where(
                Execution.caller_scope == caller_scope,
                Execution.request_id == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            response.status_code = 200
            response.headers["Idempotency-Replayed"] = "true"
            return existing
        request_id = idempotency_key
    else:
        request_id = uuid4().hex

    execution = Execution(
        project_id=project.id,
        profile_name=profile.name,
        profile_revision=profile.revision,
        caller_scope=caller_scope,
        request_id=request_id,
        priority=body.priority,
        source_revision=body.source_revision,
        context_json={
            "parameters": body.parameters,
            "caller": caller.model_dump(),
            "callback_ref": body.callback_ref,
        },
        timeout_seconds=body.timeout_seconds or profile.timeout_default,
        pipeline_run_ref=caller.run_ref,
    )
    db.add(execution)
    db.flush()
    _add_event(
        db,
        execution.id,
        EventType.EXECUTION_CREATED.value,
        {"source_revision": body.source_revision, "profile": profile.name},
    )
    db.commit()
    db.refresh(execution)
    response.headers["Location"] = f"/api/v1/executions/{execution.id}"
    return execution


@router.get("/executions", response_model=list[ExecutionOut], summary="执行列表（过滤分页）")
def list_executions(
    project: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[Execution]:
    limit = max(1, min(limit, 100))
    stmt = select(Execution).order_by(Execution.id.desc()).limit(limit).offset(offset)
    if project is not None:
        proj = db.execute(select(Project).where(Project.name == project)).scalar_one_or_none()
        if proj is None:
            raise HTTPException(status_code=404, detail=f"project '{project}' not found")
        stmt = stmt.where(Execution.project_id == proj.id)
    if status is not None:
        try:
            ExecutionStatus(status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"unknown status '{status}'")
        stmt = stmt.where(Execution.status == status)
    return list(db.execute(stmt).scalars())


@router.get("/executions/{execution_id}", response_model=ExecutionOut)
def get_execution(execution_id: int, db: Session = Depends(get_db)) -> Execution:
    return _get_or_404(db, execution_id)


@router.post(
    "/executions/{execution_id}/cancel",
    response_model=CancelOut,
    status_code=202,
    summary="异步取消：QUEUED 立即生效；已启动的记录请求，由 M1+ 的执行器执行",
)
def cancel_execution(execution_id: int, db: Session = Depends(get_db)) -> CancelOut:
    execution = _get_or_404(db, execution_id)
    if is_execution_terminal(execution.status):
        raise HTTPException(status_code=409, detail=f"execution already terminal: {execution.status}")

    now = _utcnow()
    execution.cancel_requested_at = now
    if execution.status == ExecutionStatus.QUEUED.value:
        # 尚未启动任何执行物：直达终态
        assert_execution_transition(execution.status, ExecutionStatus.CANCELLED.value)
        execution.status = ExecutionStatus.CANCELLED.value
        execution.failure_reason = FailureReason.CANCELLED_BY_USER.value
        execution.ended_at = now
        _add_event(db, execution.id, EventType.STATUS_CHANGED.value, {"status": execution.status})
    else:
        _add_event(db, execution.id, EventType.CANCEL_REQUESTED.value, {})
    db.commit()
    return CancelOut(
        id=execution.id,
        status=execution.status,
        cancel_requested=execution.cancel_requested_at is not None,
    )


# ---- M1/M3 交付的端点：契约先行，明确 501 ----
@router.get("/executions/{execution_id}/events", summary="事件流（M1）")
def list_events(execution_id: int, db: Session = Depends(get_db)) -> None:
    _get_or_404(db, execution_id)
    raise HTTPException(status_code=501, detail="events endpoint lands in M1")


@router.get("/executions/{execution_id}/logs", summary="日志分片读取（M1）")
def get_logs(execution_id: int, db: Session = Depends(get_db)) -> None:
    _get_or_404(db, execution_id)
    raise HTTPException(status_code=501, detail="logs endpoint lands in M1")


@router.get("/executions/{execution_id}/artifacts", summary="产物清单（M1）")
def get_artifacts(execution_id: int, db: Session = Depends(get_db)) -> None:
    _get_or_404(db, execution_id)
    raise HTTPException(status_code=501, detail="artifacts endpoint lands in M1")
