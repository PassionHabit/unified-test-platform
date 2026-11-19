"""/api/v1/admin：管理端操作（M2：mark-lost，需确认令牌；reconcile 手动触发）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Execution
from ...reconciler import mark_execution_lost, mark_node_lost, reconcile

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_confirm(confirm: str, expect: str) -> None:
    if confirm != expect:
        raise HTTPException(status_code=400, detail=f"confirmation mismatch: pass X-Confirm: {expect}")


@router.post("/executions/{execution_id}/mark-lost", summary="执行确认丢失（X-Confirm 头需为执行 ID）")
def admin_mark_execution_lost(
    execution_id: int,
    db: Session = Depends(get_db),
    x_confirm: str = Header(default="", alias="X-Confirm"),
) -> dict:
    _require_confirm(x_confirm, str(execution_id))
    result = mark_execution_lost(db, execution_id)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason", "rejected"))
    return result


@router.post("/nodes/{node_id}/mark-lost", summary="节点确认丢失（X-Confirm 头需为 node-lost-<id>）")
def admin_mark_node_lost(
    node_id: int,
    db: Session = Depends(get_db),
    x_confirm: str = Header(default="", alias="X-Confirm"),
) -> dict:
    _require_confirm(x_confirm, f"node-lost-{node_id}")
    result = mark_node_lost(db, node_id)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason", "rejected"))
    return result


@router.post("/reconcile", summary="手动触发一轮对账（后台周期任务之外）")
def admin_reconcile(db: Session = Depends(get_db)) -> dict:
    return reconcile(db)
