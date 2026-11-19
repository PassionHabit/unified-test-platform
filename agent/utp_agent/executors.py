"""执行器：Native（真实子进程）与 Docker 两种实现（V2.1 §4.6 JobExecutor）。

统一入口 run_argv：prepare 与主命令都走它；取消经 cancel_event（优雅→宽限→强杀）。
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from typing import Callable, Optional

from utp_shared.agent_protocol import AttemptSpec

GRACE_S = 30


class ExecutionResult:
    def __init__(self, exit_code: int, oom_killed: bool = False):
        self.exit_code = exit_code
        self.oom_killed = oom_killed


def _pump(stream, fn: Callable) -> None:
    for chunk in iter(lambda: stream.read(65536), b""):
        fn(chunk)
    stream.close()


def native_run(
    argv: list,
    cwd: str,
    env: Optional[dict],
    on_stdout: Callable,
    on_stderr: Callable,
    cancel_event: threading.Event,
    grace_s: int = GRACE_S,
) -> ExecutionResult:
    """真实子进程执行：独立进程组，SIGTERM→宽限→SIGKILL。"""
    merged = dict(os.environ)
    if env:
        merged.update(env)
    proc = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=merged,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    threads = [
        threading.Thread(target=_pump, args=(proc.stdout, on_stdout), daemon=True),
        threading.Thread(target=_pump, args=(proc.stderr, on_stderr), daemon=True),
    ]
    for t in threads:
        t.start()

    kill_at: Optional[float] = None
    while True:
        code = proc.poll()
        if code is not None:
            break
        if cancel_event.is_set() and kill_at is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            kill_at = time.time() + grace_s
        elif kill_at is not None and time.time() > kill_at:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            kill_at = time.time() + 5
        time.sleep(0.2)
    for t in threads:
        t.join(timeout=10)
    return ExecutionResult(exit_code=proc.returncode)


class DockerExecutor:
    """容器执行：真实 Docker Engine；不可用时抛出明确异常（不假装成功）。"""

    def __init__(self):
        try:
            import docker
        except ImportError as exc:
            raise RuntimeError("docker SDK not installed (pip install docker)") from exc
        self._docker = docker.from_env()
        self._docker.ping()

    def run_argv(
        self,
        spec: AttemptSpec,
        argv: list,
        on_stdout: Callable,
        on_stderr: Callable,
        cancel_event: threading.Event,
    ) -> ExecutionResult:
        resources = spec.resources
        container = self._docker.containers.run(
            spec.image,
            command=list(argv),
            environment=dict(spec.env or {}),
            detach=True,
            labels={"utp.execution_id": spec.execution_id, "utp.attempt_id": spec.attempt_id},
            mem_limit=f"{resources.memory_mb}m",
            shm_size=f"{resources.shm_mb}m",
            nano_cpus=int(resources.cpu * 1e9),
        )
        kill_at: Optional[float] = None
        while True:
            container.reload()
            if container.status in ("exited", "dead"):
                break
            if cancel_event.is_set() and kill_at is None:
                try:
                    container.stop(timeout=GRACE_S)
                except Exception:
                    pass
                kill_at = time.time() + GRACE_S + 30
            elif kill_at is not None and time.time() > kill_at:
                try:
                    container.kill()
                except Exception:
                    pass
            time.sleep(0.5)

        for chunk in container.logs(stream=True, follow=False):
            on_stdout(chunk if isinstance(chunk, bytes) else chunk.encode())
        state = (container.attrs or {}).get("State", {})
        exit_code = int(state.get("ExitCode", -1))
        oom = bool(state.get("OOMKilled", False))
        try:
            container.remove(force=True)
        except Exception:
            pass
        return ExecutionResult(exit_code=exit_code, oom_killed=oom)


def make_executor(mode: str):
    if mode == "docker":
        return DockerExecutor()
    return "native"  # native 模式直接用模块函数 native_run
