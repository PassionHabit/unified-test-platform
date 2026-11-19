"""/api/v1/services：服务目录管理（M3，管理员登记）+ /api/v1/admin/secrets。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import SecretRef, ServiceCatalog
from ...secrets import encrypt

router = APIRouter(tags=["services"])


class ServiceCreate(BaseModel):
    key: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="custom", pattern="^(preset|custom)$")
    mode: str = Field(default="async_poll", pattern="^(sync|async_poll)$")
    endpoint_ref: str = Field(min_length=1, max_length=500)
    auth_ref: Optional[str] = None
    phases: List[str] = Field(default_factory=list)
    params_schema: dict = Field(default_factory=dict)
    cleanup_ref: Optional[str] = None
    visibility: str = "public"
    enabled: bool = True


class ServiceOut(BaseModel):
    id: int
    key: str
    name: str
    kind: str
    mode: str
    endpoint_ref: str
    phases: list
    visibility: str
    enabled: bool

    model_config = {"from_attributes": True}


@router.post("/services", response_model=ServiceOut, status_code=201)
def create_service(body: ServiceCreate, db: Session = Depends(get_db)) -> ServiceCatalog:
    exists = db.query(ServiceCatalog).filter(ServiceCatalog.key == body.key).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"service '{body.key}' already exists")
    entry = ServiceCatalog(**body.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/services", response_model=list[ServiceOut])
def list_services(db: Session = Depends(get_db)) -> list:
    return list(db.query(ServiceCatalog).order_by(ServiceCatalog.id).all())


@router.delete("/services/{key}", status_code=204)
def delete_service(key: str, db: Session = Depends(get_db)) -> None:
    entry = db.query(ServiceCatalog).filter(ServiceCatalog.key == key).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(entry)
    db.commit()


# ---- 秘密引用（值永不回显） ----

class SecretPut(BaseModel):
    name: str = Field(min_length=2, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    value: str = Field(min_length=1, max_length=10000)


@router.put("/secrets/{name}", status_code=201, tags=["admin"])
def put_secret(name: str, body: SecretPut, db: Session = Depends(get_db)) -> dict:
    if name != body.name:
        raise HTTPException(status_code=422, detail="path/name mismatch")
    row = db.query(SecretRef).filter(SecretRef.name == name).first()
    if row is not None:
        row.value_encrypted = encrypt(body.value)
    else:
        db.add(SecretRef(name=name, value_encrypted=encrypt(body.value)))
    db.commit()
    return {"name": name, "stored": True}


@router.get("/secrets", tags=["admin"])
def list_secrets(db: Session = Depends(get_db)) -> list:
    return [{"name": r.name, "created_at": r.created_at} for r in db.query(SecretRef).all()]


@router.delete("/secrets/{name}", status_code=204, tags=["admin"])
def delete_secret(name: str, db: Session = Depends(get_db)) -> None:
    row = db.query(SecretRef).filter(SecretRef.name == name).first()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(row)
    db.commit()
