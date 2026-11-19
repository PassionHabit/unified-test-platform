"""Agent 主循环：长轮询领任务、并发执行、响应取消指令。"""
from __future__ import annotations

import threading
import time
from typing import Dict

from .attempt import AttemptRunner
from .client import ControlPlaneClient
from .config import get_settings


def run(once: bool = False) -> None:
    settings = get_settings()
    client = ControlPlaneClient()
    labels = [x.strip() for x in settings.labels.split(",") if x.strip()]
    print(f"[utp-agent] {settings.agent_name} mode={settings.node_type} -> {settings.control_url} labels={labels}")

    runners: Dict[str, AttemptRunner] = {}
    lock = threading.Lock()

    def _spawn(runner: AttemptRunner) -> None:
        def wrapper():
            try:
                runner.run()
            except Exception as exc:  # noqa: BLE001
                print(f"[utp-agent] attempt {runner.spec.attempt_id} crashed: {exc!r}")
            finally:
                with lock:
                    runners.pop(runner.spec.attempt_id, None)

        threading.Thread(target=wrapper, daemon=True).start()

    while True:
        try:
            with lock:
                running_ids = list(runners.keys())
            response = client.poll(
                agent_id=settings.agent_name,
                node_type=settings.node_type,
                labels=labels,
                running_attempt_ids=running_ids,
            )
            for assignment in response.assignments:
                print(f"[utp-agent] assigned attempt {assignment.attempt_id} exec {assignment.execution_id}")
                runner = AttemptRunner(assignment, client, node_mode=settings.node_type)
                with lock:
                    runners[assignment.attempt_id] = runner
                _spawn(runner)
            for command in response.commands:
                if command.cancel is not None:
                    aid = command.cancel.attempt_id
                    with lock:
                        runner = runners.get(aid)
                    if runner is not None:
                        print(f"[utp-agent] cancelling attempt {aid}")
                        runner.cancel_event.set()
                    else:
                        print(f"[utp-agent] cancel for unknown/finished attempt {aid}")
            if once:
                while True:
                    with lock:
                        if not runners:
                            return
                    time.sleep(1)
            time.sleep(response.poll_after_s)
        except KeyboardInterrupt:
            print("[utp-agent] stopped")
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[utp-agent] poll error: {exc!r}; retry in 10s")
            if once:
                raise
            time.sleep(10)
