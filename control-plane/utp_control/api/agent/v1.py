"""/agent/v1：Agent 长轮询与上报（V2.1 §8）。

- poll：注册/心跳 + 领取任务（scheduler.claim_for_node）+ 下发取消指令
- attempts/{id}/status：驱动执行状态机（execution_service）
- attempts/{id}/upload-urls：短时效预签名 PUT（日志分片/产物），无长期凭据
- attempts/{id}/log-manifest：分片清单落库（/logs 读取依据）
- attempts/{id}/artifacts：产物登记（含 sha256/size）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...execution_service import apply_attempt_report
from ...models import Artifact, Execution, ExecutionAttempt, LogManifest, WorkerNode
from ...scheduler import claim_for_node
from utp_shared.agent_protocol import (
    AttemptSpec,
    AttemptStatusReport,
    CancelCommand,
    ControlCommand,
    LogManifestUpdate,
    PollRequest,
    PollResponse,
)

router = APIRouter(prefix="/agent/v1", tags=["agent"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/poll", response_model=PollResponse, summary="长轮询：注册/心跳 + 领任务 + 控制指令")
def poll(body: PollRequest, db: Session = Depends(get_db)) -> PollResponse:
    node = db.execute(
        select(WorkerNode).where(WorkerNode.agent_id == body.agent_id)
    ).scalar_one_or_none()
    now = _utcnow()
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
        db.commit()
    else:
        node.heartbeat_at = now
        node.labels = body.labels
        node.cpu_total = body.cpu_total
        node.memory_total = body.memory_mb_total
        node.version = body.agent_version
        db.commit()

    assignments: List[AttemptSpec] = []
    # Native 节点只接 native 兼容任务（M1 无镜像隔离，Docker 节点接全部）
    slots = max(0, node.cpu_total // 2 - len(body.running_attempt_ids)) if node.type == "docker" else (
        1 - len(body.running_attempt_ids)
    )
    if slots > 0:
        for spec in claim_for_node(db, node, limit=slots):
            assignments.append(AttemptSpec.model_validate(spec))

    # 取消指令：本节点上 CANCELLING 执行的活跃 attempt
    commands: List[ControlCommand] = []
    if body.running_attempt_ids:
        rows = db.execute(
            select(ExecutionAttempt, Execution).join(
                Execution, ExecutionAttempt.execution_id == Execution.id
            ).where(
                ExecutionAttempt.id.in_([int(a) for a in body.running_attempt_ids]),
                Execution.status == "CANCELLING",
            )
        ).all()
        for attempt, execution in rows:
            commands.append(
                ControlCommand(
                    cancel=CancelCommand(
                        attempt_id=str(attempt.id), reason="user_request", grace_s=30
                    )
                )
            )

    return PollResponse(assignments=assignments, commands=commands, poll_after_s=3)


@router.post("/attempts/{attempt_id}/status", summary="状态上报（幂等，驱动状态机）")
def report_status(attempt_id: int, body: AttemptStatusReport, db: Session = Depends(get_db)) -> dict:
    result = apply_attempt_report(db, body)
    if not result.get("accepted"):
        raise HTTPException(status_code=404, detail=result.get("reason", "rejected"))
    return result


class UploadUrlRequest(BaseModel):
    keys: List[str] = Field(min_length=1, max_length=200)


class UploadUrlResponse(BaseModel):
    urls: dict


@router.post("/attempts/{attempt_id}/upload-urls", summary="申请短时效预签名 PUT")
def issue_upload_urls(attempt_id: int, body: UploadUrlRequest, db: Session = Depends(get_db)) -> UploadUrlResponse:
    attempt = db.get(ExecutionAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="unknown attempt")
    from ...storage import get_storage

    storage = get_storage()
    urls = {}
    for key in body.keys:
        # 键必须落在本 attempt 前缀下，防越权写
        prefix = f"executions/{attempt.execution_id}/attempts/{attempt.id}/"
        safe_key = key.lstrip("/")
        if not safe_key.startswith(prefix):
            raise HTTPException(status_code=403, detail=f"key outside attempt prefix: {key}")
        urls[key] = storage.presign_put(safe_key, expires_s=3600)
    return UploadUrlResponse(urls=urls)


@router.post("/attempts/{attempt_id}/log-manifest", summary="日志分片清单上报")
def report_log_manifest(attempt_id: int, body: LogManifestUpdate, db: Session = Depends(get_db)) -> dict:
    attempt = db.get(ExecutionAttempt, int(attempt_id))
    if attempt is None:
        raise HTTPException(status_code=404, detail="unknown attempt")
    manifest = db.get(LogManifest, int(attempt_id))
    if manifest is None:
        manifest = LogManifest(
            attempt_id=int(attempt_id),
            stream=body.chunks[0].stream if body.chunks else "stdout",
            chunk_count=0,
            bytes_uploaded=0,
            finalized=False,
            updated_at=_utcnow(),
        )
        db.add(manifest)
    manifest.chunk_count = max(manifest.chunk_count, len(body.chunks))
    manifest.bytes_uploaded = max(manifest.bytes_uploaded, body.bytes_total)
    manifest.finalized = body.finalized or manifest.finalized
    manifest.updated_at = _utcnow()
    db.commit()
    return {"accepted": True}


class ArtifactItem(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    key: str = Field(min_length=1, max_length=500)
    size: int = Field(ge=0)
    sha256: Optional[str] = None
    content_type: Optional[str] = None


class ArtifactRegisterRequest(BaseModel):
    items: List[ArtifactItem] = Field(min_length=1, max_length=500)


@router.post("/attempts/{attempt_id}/artifacts", summary="产物登记")
def register_artifacts(attempt_id: int, body: ArtifactRegisterRequest, db: Session = Depends(get_db)) -> dict:
    attempt = db.get(ExecutionAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="unknown attempt")
    registered = 0
    for item in body.items:
        exists = db.execute(
            select(Artifact).where(
                Artifact.execution_id == attempt.execution_id, Artifact.path == item.path
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue
        db.add(
            Artifact(
                execution_id=attempt.execution_id,
                attempt_id=attempt.id,
                path=item.path,
                storage_uri=item.key,
                sha256=item.sha256,
                size=item.size,
                content_type=item.content_type,
            )
        )
        registered += 1
    db.commit()
    return {"registered": registered}
