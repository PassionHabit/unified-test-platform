"""/api/v1/nodes：节点状态与维护（M2：排水/恢复）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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
            "maintenance_deadline": n.maintenance_deadline,
            "heartbeat_at": n.heartbeat_at,
        }
        for n in nodes
    ]


class DrainRequest(BaseModel):
    deadline_minutes: Optional[int] = Field(default=None, ge=1, le=2880)


@router.post("/nodes/{node_id}/drain", summary="维护排水：停接新任务；给 deadline 则超期强排")
def drain_node(node_id: int, body: DrainRequest, db: Session = Depends(get_db)) -> dict:
    node = db.get(WorkerNode, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    node.maintenance_state = "DRAINING"
    if body.deadline_minutes is not None:
        node.maintenance_deadline = datetime.now(timezone.utc) + timedelta(
            minutes=body.deadline_minutes
        )
    db.commit()
    return {"id": node.id, "maintenance_state": node.maintenance_state,
            "maintenance_deadline": node.maintenance_deadline}


@router.post("/nodes/{node_id}/restore", summary="恢复接单")
def restore_node(node_id: int, db: Session = Depends(get_db)) -> dict:
    node = db.get(WorkerNode, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    node.maintenance_state = "ACTIVE"
    node.maintenance_deadline = None
    db.commit()
    return {"id": node.id, "maintenance_state": node.maintenance_state}
