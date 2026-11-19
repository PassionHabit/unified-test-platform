"""Agent 主循环：M0 注册心跳 + 空转；M1 接执行。"""
from __future__ import annotations

import time

from .client import ControlPlaneClient
from .config import get_settings


def run(once: bool = False) -> None:
    settings = get_settings()
    client = ControlPlaneClient()
    labels = [x.strip() for x in settings.labels.split(",") if x.strip()]
    print(f"[utp-agent] {settings.agent_name} -> {settings.control_url} labels={labels}")

    while True:
        try:
            response = client.poll(
                agent_id=settings.agent_name,
                node_type=settings.node_type,
                labels=labels,
            )
            for assignment in response.assignments:
                print(f"[utp-agent] assignment (M1 TODO): {assignment.attempt_id}")
            for command in response.commands:
                print(f"[utp-agent] command (M1 TODO): {command}")
            if once:
                return
            time.sleep(response.poll_after_s)
        except KeyboardInterrupt:
            print("[utp-agent] stopped")
            return
        except Exception as exc:  # 网络抖动等：退避重试
            print(f"[utp-agent] poll error: {exc!r}; retry in 10s")
            if once:
                raise
            time.sleep(10)
