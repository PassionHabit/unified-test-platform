"""/api/v1/nodes：节点状态（M0 只读）；维护排水 / mark-lost 在 M2 交付。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import WorkerNode

router = APIRouter(tags=["nodes"])


@router.get("/nodes", response_model=list[dict])
def list_nodes(db: Session = Depends(get_db)) -> list[dict]:
    nodes = db.execute(select(WorkerNode).order_by(WorkerNode.id)).scalars()
    return [
        {
            "id": n.id,
            "agent_id": n.agent_id,
            "type": n.type,
            "labels": n.labels,
            "cpu_total": n.cpu_total,
            "memory_total": n.memory_total,
            "cpu_reserved": n.cpu_reserved,
            "memory_reserved": n.memory_reserved,
            "maintenance_state": n.maintenance_state,
            "heartbeat_at": n.heartbeat_at,
        }
        for n in nodes
    ]


@router.post("/nodes/{node_id}/drain", summary="维护排水（M2）")
def drain_node(node_id: int) -> None:
    raise HTTPException(status_code=501, detail="drain lands in M2")


@router.post("/nodes/{node_id}/restore", summary="恢复接单（M2）")
def restore_node(node_id: int) -> None:
    raise HTTPException(status_code=501, detail="restore lands in M2")
