"""M3 端到端（真实链路）：

1. 源码快照：本地真实 git 仓库 → 提交 branch → 固化 commit → 快照上传 →
   Agent 下载解压 → 真实执行使用快照内文件
2. prepare 步骤：装依赖类前置命令真实执行
3. 秘密引用：{"$secret": name} 经 env 注入（不出现在 spec 明文/日志）
4. 公共服务：真实本地 HTTP 服务（async_poll）before 阻断 / during 启停 / after 追踪
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.usefixtures("e2e_stack")

AGENT_SRC = str(Path(__file__).resolve().parents[2] / "agent")


@pytest.fixture(scope="module")
def api(e2e_stack):
    client = httpx.Client(trust_env=False, timeout=60, base_url=e2e_stack["api"])
    yield client
    client.close()


@pytest.fixture(scope="module")
def git_repo(tmp_path_factory):
    """真实本地 git 仓库：包含一个测试脚本与数据文件。"""
    repo = tmp_path_factory.mktemp("git-src")
    (repo / "data.txt").write_text("SNAPSHOT-CONTENT-42\n")
    script = repo / "run_test.py"
    script.write_text(
        "import os, sys\n"
        "content = open(os.path.join(os.environ['UTP_WORKSPACE_DIR'], 'data.txt')).read().strip()\n"
        "print('snapshot-loaded:', content)\n"
        "open(os.path.join(os.environ['UTP_ARTIFACTS_DIR'], 'out.txt'), 'w').write(content)\n"
    )
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"],
        check=True, capture_output=True,
    )
    return repo


@pytest.fixture(scope="module")
def fake_service_server():
    """真实外部公共服务（async_poll 协议）：POST→task_id，GET 状态，DELETE 清理。"""
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()
    state = {"tasks": {}, "deleted": [], "calls": []}

    @app.post("/svc")
    def create(req: dict):
        state["calls"].append(("create", req.get("params")))
        task_id = f"task-{len(state['tasks']) + 1}"
        state["tasks"][task_id] = "SUCCEEDED"
        return {"task_id": task_id}

    @app.post("/svc-fail")
    def create_fail(req: dict):
        task_id = f"fail-{len(state['tasks']) + 1}"
        state["tasks"][task_id] = "FAILED"
        return {"task_id": task_id}

    @app.get("/svc/{task_id}")
    @app.get("/svc-fail/{task_id}")
    def status(task_id: str):
        return {"status": state["tasks"].get(task_id, "SUCCEEDED")}

    @app.delete("/svc/{task_id}")
    @app.delete("/svc-fail/{task_id}")
    def delete(task_id: str):
        state["deleted"].append(task_id)
        return {"ok": True}

    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/docs", trust_env=False, timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    yield {"base": f"http://127.0.0.1:{port}", "state": state}


def _agent_poll(api, agent_id, running=None):
    r = api.post(
        "/agent/v1/poll",
        json={"agent_id": agent_id, "node_type": "native", "labels": [],
              "cpu_total": 2, "memory_mb_total": 4096, "running_attempt_ids": running or []},
    )
    r.raise_for_status()
    return r.json()


def _wait_terminal(api, exec_id, timeout=90):
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        body = api.get(f"/api/v1/executions/{exec_id}").json()
        if body["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return body
        time.sleep(1)
    raise AssertionError(f"not terminal: {body}")


def _run_attempt(api, spec):
    from utp_agent.attempt import AttemptRunner
    from utp_agent.client import ControlPlaneClient
    from utp_shared.agent_protocol import AttemptSpec

    cp = ControlPlaneClient(base_url=str(api.base_url).rstrip("/"))
    AttemptRunner(AttemptSpec.model_validate(spec), cp, node_mode="native").run()


class TestSnapshotE2E:
    def test_git_snapshot_prepare_secret(self, api, git_repo):
        # 秘密入库
        r = api.put("/api/v1/secrets/ssh-key-demo", json={"name": "ssh-key-demo", "value": "SECRET-VALUE-XYZ"})
        assert r.status_code == 201, r.text

        # 项目 + Profile：prepare 步骤 + 快照内脚本 + 秘密 env
        api.post("/api/v1/projects", json={
            "name": "git-e2e", "source_type": "git", "repository_ref": str(git_repo)})
        r = api.post("/api/v1/projects/git-e2e/profiles", json={
            "name": "default",
            "runtime_image_ref": "python:3.12",
            "prepare_argv": [sys.executable, "-c", "print('prepare-step-ok')"],
            "argv": [sys.executable, "run_test.py"],
        })
        assert r.status_code == 201, r.text

        # 提交：branch=main → 必须固化为 commit
        r = api.post("/api/v1/executions", json={
            "project_id": "git-e2e", "source_revision": "main",
            "parameters": {"environment": {"SSH_KEY": {"$secret": "ssh-key-demo"}}},
            "caller": {"type": "human"},
        })
        assert r.status_code == 202, r.text
        exec_id = r.json()["id"]
        assert len(r.json()["source_revision"]) == 40, "branch 必须固化为 commit"

        poll = _agent_poll(api, "m3-agent")
        assert len(poll["assignments"]) == 1
        spec = poll["assignments"][0]
        assert spec["snapshot_key"], "解析成功必须有 snapshot_key"
        # 秘密以明文进 spec env（仅经受控通道下发，不落库/不进日志/context）
        assert spec["env"].get("SSH_KEY") == "SECRET-VALUE-XYZ"

        _run_attempt(api, spec)
        body = _wait_terminal(api, exec_id)
        assert body["status"] == "COMPLETED", body

        # 快照真实生效：日志含 prepare 输出 + 快照文件内容
        logs = api.get(f"/api/v1/executions/{exec_id}/logs").text
        assert "prepare-step-ok" in logs
        assert "snapshot-loaded: SNAPSHOT-CONTENT-42" in logs
        # 产物来自快照内脚本写入
        arts = api.get(f"/api/v1/executions/{exec_id}/artifacts").json()
        assert any(a["path"] == "out.txt" for a in arts)

        # execution-context.json（含环境）永不收集
        assert all(a["path"] != "execution-context.json" for a in arts)

        # 二次提交命中快照缓存（同 commit），随即取消避免残留排队
        r2 = api.post("/api/v1/executions", json={
            "project_id": "git-e2e", "source_revision": "main", "caller": {"type": "human"}})
        assert r2.status_code == 202
        assert r2.json()["source_revision"] == body["source_revision"]
        api.post(f"/api/v1/executions/{r2.json()['id']}/cancel")


class TestServiceBindings:
    def test_before_blocks_on_failure(self, api, fake_service_server):
        base = fake_service_server["base"]
        api.post("/api/v1/services", json={
            "key": "svc-fail-demo", "name": "失败服务", "mode": "async_poll",
            "endpoint_ref": f"{base}/svc-fail", "phases": ["before"]})
        api.post("/api/v1/projects", json={
            "name": "svc-e2e", "source_type": "git", "repository_ref": "nowhere"})
        api.post("/api/v1/projects/svc-e2e/profiles", json={
            "runtime_image_ref": "python:3.12", "argv": ["true"],
            "service_bindings": {"bindings": [
                {"phase": "before", "service": "svc-fail-demo", "on_failure": "block"}]}})
        r = api.post("/api/v1/executions", json={
            "project_id": "svc-e2e", "source_revision": "main", "caller": {"type": "human"}})
        exec_id = r.json()["id"]

        poll = _agent_poll(api, "svc-agent")
        assert poll["assignments"] == [], "before 失败（block）不应下发任务"
        body = _wait_terminal(api, exec_id)
        assert body["status"] == "FAILED"
        assert body["failure_reason"] == "SERVICE_BEFORE_FAILED"

    def test_during_after_lifecycle(self, api, fake_service_server):
        base = fake_service_server["base"]
        state = fake_service_server["state"]
        state["calls"].clear()
        state["deleted"].clear()
        api.post("/api/v1/services", json={
            "key": "svc-ok-demo", "name": "正常服务", "mode": "async_poll",
            "endpoint_ref": f"{base}/svc", "phases": ["during", "after"]})
        api.post("/api/v1/projects", json={
            "name": "svc2-e2e", "source_type": "git", "repository_ref": "nowhere"})
        api.post("/api/v1/projects/svc2-e2e/profiles", json={
            "runtime_image_ref": "python:3.12", "argv": [sys.executable, "-c", "print('svc-test-run')"],
            "service_bindings": {"bindings": [
                {"phase": "during", "service": "svc-ok-demo"},
                {"phase": "after", "service": "svc-ok-demo"}]}})
        r = api.post("/api/v1/executions", json={
            "project_id": "svc2-e2e", "source_revision": "main", "caller": {"type": "human"}})
        exec_id = r.json()["id"]

        poll = _agent_poll(api, "svc2-agent")
        assert len(poll["assignments"]) == 1
        _run_attempt(api, poll["assignments"][0])
        body = _wait_terminal(api, exec_id)
        assert body["status"] == "COMPLETED", body

        # after 服务被真实调用过；during 伴生任务被清理（DELETE）
        time.sleep(1)
        creates = [c for c in state["calls"] if c[0] == "create"]
        assert len(creates) >= 2, f"during+after 均应调用: {state}"
        assert len(state["deleted"]) >= 1, "during 任务应被清理"
