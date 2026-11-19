"""Attempt 编排：一个 assignment 的完整生命周期（V2.1 §7 线性步骤的 Agent 侧）。

STARTING → prepare(可选) → RUNNING → 产物收集上传 → EXITED/CANCELLED。
看门狗：deadline_at 到期置 cancel_event（本地执法，分区下有效）。
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

import httpx

from .client import ControlPlaneClient
from .config import get_settings
from .executors import native_run
from .logstore import ChunkedLogUploader
from utp_shared.agent_protocol import AttemptSpec, AttemptStatus, AttemptStatusReport

# 永不收集进产物的路径（安全兜底，V2.1 §6）
ALWAYS_EXCLUDE = {"execution-context.json"}


def _report(client, attempt_id, execution_id, status, **kw) -> None:
    payload = {
        "report_id": uuid4().hex,
        "attempt_id": attempt_id,
        "execution_id": execution_id,
        "status": status.value,
    }
    payload.update(kw)
    client.report_status(AttemptStatusReport.model_validate(payload))


class AttemptRunner:
    def __init__(self, spec: AttemptSpec, client: ControlPlaneClient, node_mode: str = "native"):
        self.spec = spec
        self.client = client
        self.settings = get_settings()
        base = os.path.expanduser(self.settings.work_dir)
        self.workdir = os.path.join(base, spec.attempt_id)
        self.workspace = os.path.join(self.workdir, "workspace")
        self.artifacts = os.path.join(self.workdir, "artifacts")
        self.cancel_event = threading.Event()
        self._mode = node_mode
        self._docker = None
        if node_mode == "docker":
            from .executors import DockerExecutor

            self._docker = DockerExecutor()

    # ---- 生命周期 ----
    def run(self) -> None:
        os.makedirs(self.workspace, exist_ok=True)
        os.makedirs(self.artifacts, exist_ok=True)
        self._write_context()
        _report(self.client, self.spec.attempt_id, self.spec.execution_id, AttemptStatus.STARTING)

        stdout = ChunkedLogUploader(self.client, self.spec.attempt_id, self.spec.execution_id,
                                    "stdout", self.workdir)
        stderr = ChunkedLogUploader(self.client, self.spec.attempt_id, self.spec.execution_id,
                                    "stderr", self.workdir)

        watchdog = threading.Thread(target=self._watchdog, daemon=True)
        watchdog.start()

        exit_code = -1
        try:
            if self.spec.prepare is not None:
                pre = self._execute(self.spec.prepare.argv, stdout, stderr,
                                    timeout=self.spec.prepare.timeout_s)
                if pre != 0:
                    _report(self.client, self.spec.attempt_id, self.spec.execution_id,
                            AttemptStatus.EXITED, exit_code=pre, message="prepare failed")
                    return

            _report(self.client, self.spec.attempt_id, self.spec.execution_id, AttemptStatus.RUNNING)
            exit_code = self._execute(self.spec.argv, stdout, stderr)
        finally:
            stdout.finalize()
            stderr.finalize()

        if self.cancel_event.is_set():
            _report(self.client, self.spec.attempt_id, self.spec.execution_id,
                    AttemptStatus.CANCELLED, exit_code=exit_code)
            return

        try:
            self._collect_artifacts()
        except Exception as exc:  # noqa: BLE001
            import traceback

            print(f"[utp-agent] artifact collection failed: {exc!r}")
            traceback.print_exc()

        _report(self.client, self.spec.attempt_id, self.spec.execution_id,
                AttemptStatus.EXITED, exit_code=exit_code)

    def _execute(self, argv: List[str], stdout, stderr, timeout: Optional[int] = None) -> int:
        if self._docker is not None:
            result = self._docker.run_argv(
                self.spec, argv, stdout.write, stderr.write, self.cancel_event
            )
            return result.exit_code

        # native：软超时到点触发优雅取消路径；注入平台约定变量（Native 模式的产物/工作区约定）
        env = dict(self.spec.env or {})
        env["UTP_ARTIFACTS_DIR"] = self.artifacts
        env["UTP_WORKSPACE_DIR"] = self.workspace
        timer = None
        if timeout is not None:
            timer = threading.Timer(timeout, self.cancel_event.set)
            timer.daemon = True
            timer.start()
        try:
            result = native_run(
                argv, self.workspace, env,
                stdout.write, stderr.write, self.cancel_event,
            )
            return result.exit_code
        finally:
            if timer is not None:
                timer.cancel()

    # ---- 看门狗（V2.1 §8） ----
    def _watchdog(self) -> None:
        if not self.spec.deadline_at:
            return
        deadline = self.spec.deadline_at
        while not self.cancel_event.is_set():
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                self.cancel_event.set()
                return
            time.sleep(min(5, max(0.5, remaining / 4)))

    # ---- 产物 ----
    def _write_context(self) -> None:
        context = {"environment": self.spec.env, "runtime": {"artifacts_dir": self.spec.artifacts_dir}}
        with open(os.path.join(self.workspace, "execution-context.json"), "w") as fh:
            json.dump(context, fh, ensure_ascii=False, indent=2)

    def _collect_artifacts(self) -> None:
        exclude = set(ALWAYS_EXCLUDE)
        items = []
        prefix = f"executions/{self.spec.execution_id}/attempts/{self.spec.attempt_id}/artifacts"
        for root, _dirs, files in os.walk(self.artifacts):
            for name in files:
                path = os.path.join(root, name)
                rel = os.path.relpath(path, self.artifacts)
                if rel in exclude:
                    continue
                items.append({
                    "path": rel,
                    "key": f"{prefix}/{rel}",
                    "size": os.path.getsize(path),
                    "sha256": self._sha256(path),
                    "content_type": mimetypes.guess_type(name)[0] or "application/octet-stream",
                })
        if not items:
            return
        http = httpx.Client(trust_env=False, timeout=300)
        try:
            for i in range(0, len(items), 50):
                batch = items[i:i + 50]
                resp = self.client._request_json(
                    "POST", f"/agent/v1/attempts/{self.spec.attempt_id}/upload-urls",
                    json={"keys": [it["key"] for it in batch]},
                )
                for it in batch:
                    url = resp["urls"][it["key"]]
                    with open(os.path.join(self.artifacts, it["path"]), "rb") as fh:
                        put = http.put(url, content=fh)
                        put.raise_for_status()
            self.client._request_json(
                "POST", f"/agent/v1/attempts/{self.spec.attempt_id}/artifacts",
                json={"items": items},
            )
        finally:
            http.close()

    @staticmethod
    def _sha256(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
