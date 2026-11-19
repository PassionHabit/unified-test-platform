"""公共服务调用运行时（M3，V2.1 §10）。

服务目录条目由管理员登记；平台只做编排调用与追踪，不实现服务本身。
- sync：POST endpoint，2xx 视为成功
- async_poll：POST → {task_id}；GET endpoint/{task_id} 轮询
  {status: SUCCEEDED|FAILED|RUNNING}（终态映射可配）；DELETE endpoint/{task_id} 清理
before：顺序调用，失败按绑定配置阻断启动；
during：启动时调用 + 结束时清理（尽力而为）；
after：结束后调用（尽力而为）。所有清理幂等，失败单独记录不阻塞终态。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from .models import Execution, ServiceCatalog, ServiceInvocation

TERMINAL_OK = {"SUCCEEDED", "SUCCESS", "OK", "succeeded", "success", "done"}
TERMINAL_FAIL = {"FAILED", "ERROR", "failed", "error"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _client() -> httpx.Client:
    return httpx.Client(trust_env=False, timeout=30)


def invoke_service(
    db: Session,
    execution: Execution,
    entry: ServiceCatalog,
    phase: str,
    params: Optional[dict] = None,
    poll_timeout_s: int = 600,
) -> ServiceInvocation:
    """按目录条目模式调用外部服务并落库追踪。失败抛 ServiceInvokeError。"""
    invocation = ServiceInvocation(
        execution_id=execution.id,
        service_ref=entry.key,
        phase=phase,
        status="running",
        started_at=_utcnow(),
        request_ref=str(params or {}),
    )
    db.add(invocation)
    db.commit()

    class ServiceInvokeError(RuntimeError):
        pass

    try:
        with _client() as http:
            headers = {}
            if entry.auth_ref:
                headers["Authorization"] = entry.auth_ref  # M3：登记时配置的令牌/凭据引用
            resp = http.post(entry.endpoint_ref, json={"execution_id": execution.id, "params": params or {}},
                             headers=headers)
            resp.raise_for_status()
            if entry.mode == "sync":
                invocation.status = "succeeded"
                invocation.response_ref = resp.text[:500]
            else:  # async_poll
                task_id = resp.json().get("task_id")
                if not task_id:
                    raise ServiceInvokeError("async service did not return task_id")
                invocation.external_task_id = task_id
                deadline = time.time() + poll_timeout_s
                status = "RUNNING"
                while time.time() < deadline:
                    poll = http.get(f"{entry.endpoint_ref}/{task_id}", headers=headers)
                    poll.raise_for_status()
                    status = str(poll.json().get("status", ""))
                    if status in TERMINAL_FAIL:
                        raise ServiceInvokeError(f"service task {task_id} failed")
                    if status in TERMINAL_OK:
                        break
                    time.sleep(2)
                else:
                    raise ServiceInvokeError(f"service task {task_id} poll timeout")
                invocation.status = "succeeded"
        invocation.ended_at = _utcnow()
        db.commit()
        return invocation
    except Exception as exc:
        invocation.status = "failed"
        invocation.response_ref = repr(exc)[:500]
        invocation.ended_at = _utcnow()
        db.commit()
        raise ServiceInvokeError(f"{entry.key}: {exc}") from exc


def cleanup_invocation(db: Session, invocation: ServiceInvocation) -> None:
    """清理（幂等，尽力而为）：async 型 DELETE task；失败仅记录。"""
    if invocation.status in ("cleaned", "failed_clean"):
        return
    entry = db.query(ServiceCatalog).filter(ServiceCatalog.key == invocation.service_ref).first()
    if entry is None or not invocation.external_task_id:
        invocation.status = "cleaned"
        db.commit()
        return
    try:
        with _client() as http:
            http.delete(f"{entry.endpoint_ref}/{invocation.external_task_id}", timeout=15)
        invocation.status = "cleaned"
    except Exception:
        invocation.status = "failed_clean"  # 单独记录，不阻塞
    db.commit()


def run_before_services(db: Session, execution: Execution, bindings: list) -> list:
    """顺序调用 before 服务；on_failure=block 的失败会抛异常阻断启动。"""
    for binding in bindings or []:
        if binding.get("phase") != "before":
            continue
        entry = db.query(ServiceCatalog).filter(
            ServiceCatalog.key == binding.get("service"),
            ServiceCatalog.enabled.is_(True),
        ).first()
        if entry is None:
            continue
        try:
            invoke_service(db, execution, entry, "before", binding.get("params"))
        except Exception:
            if binding.get("on_failure", "block") != "continue":
                raise
    return []


def run_after_services(db: Session, execution: Execution, bindings: list) -> None:
    """after + during 清理：尽力而为，任何失败不抛出。"""
    for binding in bindings or []:
        phase = binding.get("phase")
        if phase not in ("after", "during"):
            continue
        entry = db.query(ServiceCatalog).filter(
            ServiceCatalog.key == binding.get("service"),
            ServiceCatalog.enabled.is_(True),
        ).first()
        if entry is None:
            continue
        try:
            if phase == "after":
                invoke_service(db, execution, entry, "after", binding.get("params"))
            else:  # during：启动于 claim 阶段，这里只做清理
                for inv in db.query(ServiceInvocation).filter(
                    ServiceInvocation.execution_id == execution.id,
                    ServiceInvocation.service_ref == entry.key,
                    ServiceInvocation.phase == "during",
                ).all():
                    cleanup_invocation(db, inv)
        except Exception:
            continue  # 尽力而为


def start_during_services(db: Session, execution: Execution, bindings: list) -> None:
    """claim 阶段启动 during 服务（尽力而为，失败不阻塞执行）。"""
    for binding in bindings or []:
        if binding.get("phase") != "during":
            continue
        entry = db.query(ServiceCatalog).filter(
            ServiceCatalog.key == binding.get("service"),
            ServiceCatalog.enabled.is_(True),
        ).first()
        if entry is None:
            continue
        try:
            invoke_service(db, execution, entry, "during", binding.get("params"))
        except Exception:
            continue
