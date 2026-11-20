"""/metrics（Prometheus 文本）+ 令牌与镜像库管理（M4）。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...auth import issue_token, require_admin
from ...db import get_db
from ...models import ApiToken, Department, Execution, ResourceReservation, RuntimeImage, WorkerNode

router = APIRouter(tags=["ops"])


@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus 指标")
def metrics(db: Session = Depends(get_db)) -> str:
    lines: List[str] = []

    def gauge(name: str, value, help_text: str, labels: str = "") -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name}{labels} {value}")

    status_rows = db.execute(
        select(Execution.status, func.count(Execution.id)).group_by(Execution.status)
    ).all()
    for status, count in status_rows:
        gauge("utp_executions", count, "executions by status", f'{{status="{status}"}}')

    nodes = db.execute(select(WorkerNode)).scalars().all()
    active = [n for n in nodes if n.maintenance_state == "ACTIVE"]
    gauge("utp_nodes_total", len(nodes), "registered worker nodes")
    gauge("utp_nodes_active", len(active), "nodes in ACTIVE state")
    for n in nodes:
        gauge("utp_node_cpu_reserved", n.cpu_reserved, "reserved cpu cores",
              f'{{agent_id="{n.agent_id}"}}')
        gauge("utp_node_cpu_total", n.cpu_total, "total cpu cores",
              f'{{agent_id="{n.agent_id}"}}')
        gauge("utp_node_memory_reserved_mb", n.memory_reserved, "reserved memory MB",
              f'{{agent_id="{n.agent_id}"}}')

    reservations = db.execute(
        select(func.count(ResourceReservation.id)).where(ResourceReservation.state == "active")
    ).scalar_one()
    gauge("utp_reservations_active", reservations, "active resource reservations")

    return "\n".join(lines) + "\n"


# ---- API 令牌管理（admin） ----

class TokenCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    role: str = Field(default="human", pattern="^(admin|human|pipeline|agent)$")
    department_id: Optional[int] = None


@router.post("/tokens", status_code=201, summary="签发令牌（明文仅此一次）")
def create_token(body: TokenCreate, db: Session = Depends(get_db),
                 principal=Depends(require_admin)) -> dict:
    exists = db.query(ApiToken).filter(ApiToken.name == body.name).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail="token name exists")
    token = issue_token(db, body.name, body.role, body.department_id, created_by=principal.name)
    return {"name": body.name, "role": body.role, "token": token}


@router.get("/tokens", summary="令牌列表（不含明文/哈希）")
def list_tokens(db: Session = Depends(get_db), principal=Depends(require_admin)) -> list:
    return [{"id": t.id, "name": t.name, "role": t.role,
             "department_id": t.department_id, "enabled": t.enabled} for t in db.query(ApiToken).all()]


@router.delete("/tokens/{name}", status_code=204, summary="吊销令牌")
def revoke_token(name: str, db: Session = Depends(get_db), principal=Depends(require_admin)) -> None:
    row = db.query(ApiToken).filter(ApiToken.name == name).first()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    row.enabled = False
    db.commit()


# ---- 镜像库（M4：引用登记；Dockerfile 构建流水线待接入 Harbor） ----

class ImageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tag: str = Field(default="latest", max_length=100)
    source: str = Field(default="reference", pattern="^(official|reference|build)$")
    ref_uri: str = Field(min_length=1, max_length=500)
    digest: Optional[str] = None
    department_id: Optional[int] = None
    owner: Optional[str] = None
    visibility: str = Field(default="department", pattern="^(public|department|private)$")


@router.post("/images", status_code=201, summary="登记镜像（引用现成地址即用）")
def create_image(body: ImageCreate, db: Session = Depends(get_db),
                 principal=Depends(require_admin)) -> dict:
    exists = db.query(RuntimeImage).filter(
        RuntimeImage.name == body.name, RuntimeImage.tag == body.tag).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail="image exists")
    row = RuntimeImage(**body.model_dump())
    db.add(row)
    db.commit()
    return {"id": row.id, "name": row.name, "tag": row.tag, "source": row.source}


@router.get("/images", summary="镜像列表")
def list_images(db: Session = Depends(get_db), principal=Depends(require_admin)) -> list:
    return [{"id": i.id, "name": i.name, "tag": i.tag, "source": i.source,
             "ref_uri": i.ref_uri, "visibility": i.visibility, "status": i.status}
            for i in db.query(RuntimeImage).all()]
