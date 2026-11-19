"""/api/v1/admin：管理端操作（mark-lost 等在 M2 交付）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/executions/{execution_id}/mark-lost", summary="确认丢失（M2，需确认令牌）")
def mark_execution_lost(execution_id: int) -> None:
    raise HTTPException(status_code=501, detail="mark-lost lands in M2")


@router.post("/nodes/{node_id}/mark-lost", summary="节点确认丢失（M2，需确认令牌）")
def mark_node_lost(node_id: int) -> None:
    raise HTTPException(status_code=501, detail="mark-lost lands in M2")
