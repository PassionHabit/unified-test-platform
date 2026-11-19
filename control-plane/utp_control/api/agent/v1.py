"""/agent/v1：Agent 长轮询与上报（V2.1 §8）。

M0：注册/心跳落库 + 空轮询应答；assignment 分发与 mTLS 认证在 M1/M2 交付。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import WorkerNode
from utp_shared.agent_protocol import (
    AttemptStatusReport,
    LogManifestUpdate,
    PollRequest,
    PollResponse,
)

router = APIRouter(prefix="/agent/v1", tags=["agent"])


@router.post("/poll", response_model=PollResponse, summary="长轮询：兼作注册与心跳")
def poll(body: PollRequest, db: Session = Depends(get_db)) -> PollResponse:
    node = db.execute(
        select(WorkerNode).where(WorkerNode.agent_id == body.agent_id)
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if node is None:
        node = WorkerNode(
            agent_id=body.agent_id,
            type=body.node_type,
            labels=body.labels,
            cpu_total=body.cpu_total,
            memory_total=body.memory_mb_total,
            version=body.agent_version,
            heartbeat_at=now,
        )
        db.add(node)
    else:
        node.heartbeat_at = now
        node.labels = body.labels
        node.cpu_total = body.cpu_total
        node.memory_total = body.memory_mb_total
        node.version = body.agent_version
    db.commit()
    # M0 无调度器：应答空分配。M1 起从队列领取并构造 AttemptSpec。
    return PollResponse(assignments=[], commands=[], poll_after_s=5)


@router.post("/attempts/{attempt_id}/status", status_code=202, summary="Attempt 状态上报")
def report_status(attempt_id: str, body: AttemptStatusReport) -> dict:
    # M1 起驱动状态机与对账；M0 仅确认接收。
    return {"accepted": True, "attempt_id": attempt_id}


@router.post("/attempts/{attempt_id}/log-manifest", status_code=202, summary="日志分片清单上报")
def report_log_manifest(attempt_id: str, body: LogManifestUpdate) -> dict:
    # M1 起写 log_manifests 供 /logs 读取；M0 仅确认接收。
    return {"accepted": True, "attempt_id": attempt_id}
