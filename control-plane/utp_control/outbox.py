"""回调 outbox（M4，V2.1 §9）：至少一次投递 + 事件 ID 去重（接收方职责）。

finalize 时写入 callback_delivery；后台线程按退避重试投递 HTTP POST；
成功/永久失败（超过最大次数）终态化。回调目标白名单防 SSRF（V2.1 §11）。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import CallbackDelivery, Execution

MAX_ATTEMPTS = 10
BACKOFF_S = [5, 15, 60, 300, 900, 1800, 3600, 7200, 14400, 28800]


def enqueue_callback(db: Session, execution_id: int, event_type: str, target_ref: str) -> None:
    db.add(CallbackDelivery(execution_id=execution_id, target_ref=target_ref,
                            event_type=event_type, state="pending"))
    db.commit()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _target_allowed(target: str) -> bool:
    """回调目标白名单：settings.callback_allowlist（逗号分隔前缀）；空 = 全禁。"""
    allow = get_settings().callback_allowlist
    if not allow:
        return False
    prefixes = [x.strip() for x in allow.split(",") if x.strip()]
    return any(target.startswith(p) for p in prefixes)


def deliver_pending(db: Session, limit: int = 20) -> dict:
    """投递一批到期回调。返回统计。"""
    now = _utcnow()
    rows = (
        db.execute(
            select(CallbackDelivery, Execution)
            .join(Execution, CallbackDelivery.execution_id == Execution.id)
            .where(
                CallbackDelivery.state == "pending",
                (CallbackDelivery.next_retry_at.is_(None))
                | (CallbackDelivery.next_retry_at <= now),
            )
            .limit(limit)
        )
        .all()
    )
    stats = {"delivered": 0, "retry": 0, "dead": 0, "blocked": 0}
    for delivery, execution in rows:
        if not _target_allowed(delivery.target_ref):
            delivery.state = "blocked"
            stats["blocked"] += 1
            db.commit()
            continue

        payload = {
            "event_id": f"cb-{delivery.id}",
            "event_type": delivery.event_type,
            "execution_id": execution.id,
            "status": execution.status,
            "outcome": execution.outcome,
            "failure_reason": execution.failure_reason,
        }
        try:
            with httpx.Client(trust_env=False, timeout=15) as http:
                resp = http.post(delivery.target_ref, json=payload)
                resp.raise_for_status()
            delivery.state = "delivered"
            delivery.attempt_count += 1
            stats["delivered"] += 1
        except Exception:
            delivery.attempt_count += 1
            if delivery.attempt_count >= MAX_ATTEMPTS:
                delivery.state = "dead"
                stats["dead"] += 1
            else:
                backoff = BACKOFF_S[min(delivery.attempt_count - 1, len(BACKOFF_S) - 1)]
                delivery.next_retry_at = datetime.fromtimestamp(time.time() + backoff, tz=timezone.utc)
                stats["retry"] += 1
        db.commit()
    return stats


def start_outbox_worker(get_sessionmaker_factory):
    """后台投递线程；返回 stop 函数。"""
    import threading

    stop = threading.Event()

    def _loop():
        while not stop.wait(max(1, get_settings().outbox_interval_s)):
            try:
                s = get_sessionmaker_factory()()
                try:
                    deliver_pending(s)
                finally:
                    s.close()
            except Exception:
                pass

    threading.Thread(target=_loop, daemon=True, name="utp-outbox").start()
    return stop
