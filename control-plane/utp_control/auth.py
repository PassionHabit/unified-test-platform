"""认证与授权（M4，V2.1 §13）。

- API Token：sha256 哈希存储，`Authorization: Bearer <token>`；角色 admin/human/pipeline/agent
- 部门隔离：human/pipeline 令牌只能访问本部门项目；admin 全量
- 开关：UTP_AUTH_ENABLED=false 时全部放行（本地开发/测试；生产必须开启）
- SSO/LDAP：以 `resolve_external_identity` 钩子接入（公司接入方式确认后实现）
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import ApiToken


class Principal:
    def __init__(self, role: str, department_id: Optional[int], name: str = "anonymous"):
        self.role = role
        self.department_id = department_id
        self.name = name

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


ANONYMOUS = Principal(role="admin", department_id=None)  # auth 关闭时的默认主体


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, name: str, role: str, department_id: Optional[int], created_by: str = "") -> str:
    """生成令牌（明文只出现一次），落库存哈希。"""
    token = "utp_" + secrets.token_urlsafe(32)
    db.add(ApiToken(name=name, token_hash=hash_token(token), role=role,
                    department_id=department_id, created_by=created_by))
    db.commit()
    return token


def _resolve_external_identity(request: Request) -> Optional[Principal]:
    """SSO/LDAP 接入点：公司接入方式确认后在此实现（如解析网关注入的头）。"""
    return None


def require_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    from .config import get_settings

    if not get_settings().auth_enabled:
        return ANONYMOUS

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = header[7:]
    row = db.query(ApiToken).filter(
        ApiToken.token_hash == hash_token(token), ApiToken.enabled.is_(True)
    ).first()
    if row is None:
        raise HTTPException(status_code=401, detail="invalid token")
    return Principal(role=row.role, department_id=row.department_id, name=row.name)


def require_admin(principal: Principal = Depends(require_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin required")
    return principal


def check_project_access(principal: Principal, project_department_id: int) -> None:
    """部门隔离：非 admin 只能访问本部门项目。auth 关闭时 principal 为 admin 直接过。"""
    if principal.is_admin:
        return
    if principal.department_id != project_department_id:
        raise HTTPException(status_code=403, detail="cross-department access denied")
