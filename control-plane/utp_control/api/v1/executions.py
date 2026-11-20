"""/api/v1/executions：提交（幂等）、查询、列表、取消。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Artifact, Execution, ExecutionEvent, ExecutionProfile, ExecutionResult, LogManifest, Project
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

    # M3：版本解析固化（branch/tag → 精确 commit / svn revision）。
    # 尽力而为：解析失败保留原值并记事件——仓库暂不可达不应阻塞排队；
    # 快照阶段会真实拉取并显式失败（SOURCE_FETCH_FAILED），不吞错误。
    source_revision = body.source_revision
    revision_note = None
    source_resolved = False
    try:
        from ... import source_manager

        source_revision = source_manager.resolve_revision(
            project.source_type, project.repository_ref, body.source_revision
        )
        source_resolved = True
    except Exception as exc:  # noqa: BLE001
        revision_note = f"resolve failed, kept raw: {str(exc)[:150]}"

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
        source_revision=source_revision,
        context_json={
            "parameters": body.parameters,
            "caller": caller.model_dump(),
            "callback_ref": body.callback_ref,
            "source_resolved": source_resolved,
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
        {"source_revision": source_revision, "profile": profile.name,
         **({"revision_note": revision_note} if revision_note else {})},
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
        _add_event(db, execution.id, EventType.EXECUTION_FINALIZED.value, {"status": execution.status})
        # QUEUED 快速路径也入队回调：流水线需要知道任务未执行
        callback_ref = (execution.context_json or {}).get("callback_ref")
        if callback_ref:
            try:
                from ...outbox import enqueue_callback

                enqueue_callback(db, execution.id, "execution.finalized", callback_ref)
            except Exception:
                pass
    elif execution.status in (ExecutionStatus.PREPARING.value, ExecutionStatus.STARTING.value,
                              ExecutionStatus.RUNNING.value, ExecutionStatus.RECONCILING.value):
        assert_execution_transition(execution.status, ExecutionStatus.CANCELLING.value)
        execution.status = ExecutionStatus.CANCELLING.value
        _add_event(db, execution.id, EventType.CANCEL_REQUESTED.value, {})
    else:
        _add_event(db, execution.id, EventType.CANCEL_REQUESTED.value, {})
    db.commit()
    return CancelOut(
        id=execution.id,
        status=execution.status,
        cancel_requested=execution.cancel_requested_at is not None,
    )


# ---- 事件 / 日志 / 产物（M1 实现） ----
@router.get("/executions/{execution_id}/events", summary="事件流")
def list_events(execution_id: int, limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    _get_or_404(db, execution_id)
    limit = max(1, min(limit, 500))
    events = (
        db.execute(
            select(ExecutionEvent)
            .where(ExecutionEvent.execution_id == execution_id)
            .order_by(ExecutionEvent.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "payload": e.payload,
            "created_at": e.created_at,
        }
        for e in reversed(events)
    ]


def _latest_attempt(db: Session, execution_id: int):
    from ...models import ExecutionAttempt

    return (
        db.execute(
            select(ExecutionAttempt)
            .where(ExecutionAttempt.execution_id == execution_id)
            .order_by(ExecutionAttempt.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


@router.get("/executions/{execution_id}/logs", summary="日志：已上传分片读取")
def get_logs(
    execution_id: int,
    stream: str = "stdout",
    chunk: Optional[int] = None,
    db: Session = Depends(get_db),
):
    from fastapi.responses import PlainTextResponse

    _get_or_404(db, execution_id)
    attempt = _latest_attempt(db, execution_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="no attempt yet")
    manifest = db.get(LogManifest, attempt.id)
    if manifest is None or manifest.chunk_count == 0:
        raise HTTPException(status_code=404, detail="no log chunks uploaded yet")

    from ...storage import get_storage, StorageError

    storage = get_storage()
    base = f"executions/{execution_id}/attempts/{attempt.id}"
    if chunk is None:
        chunks = list(range(manifest.chunk_count))
    else:
        if chunk < 0 or chunk >= manifest.chunk_count:
            raise HTTPException(status_code=404, detail=f"chunk out of range 0..{manifest.chunk_count - 1}")
        chunks = [chunk]
    parts = []
    for idx in chunks:
        key = f"{base}/{stream}/{idx:06d}.log"
        try:
            parts.append(storage.get_bytes(key).decode("utf-8", "replace"))
        except StorageError:
            parts.append(f"\n[chunk {idx} unavailable]\n")
    return PlainTextResponse("".join(parts))


@router.get("/executions/{execution_id}/artifacts", summary="产物清单（可附预签名下载链接）")
def get_artifacts(execution_id: int, download: bool = False, db: Session = Depends(get_db)) -> list[dict]:
    _get_or_404(db, execution_id)
    items = db.execute(select(Artifact).where(Artifact.execution_id == execution_id)).scalars().all()
    result = []
    for a in items:
        item = {
            "path": a.path,
            "size": a.size,
            "sha256": a.sha256,
            "content_type": a.content_type,
            "key": a.storage_uri,
        }
        if download:
            from ...storage import get_storage

            item["download_url"] = get_storage().presign_get(a.storage_uri, expires_s=1800)
        result.append(item)
    return result


@router.get("/executions/{execution_id}/result", summary="轻量结果摘要")
def get_result(execution_id: int, db: Session = Depends(get_db)) -> dict:
    _get_or_404(db, execution_id)
    result = db.execute(
        select(ExecutionResult).where(ExecutionResult.execution_id == execution_id)
    ).scalars().first()
    if result is None:
        raise HTTPException(status_code=404, detail="no result summary (not parsed or NOT_EVALUATED)")
    return {
        "report_type": result.report_type,
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "skipped": result.skipped,
        "failures": (result.failures_json or {}).get("cases", []),
        "parsed_at": result.parsed_at,
    }
