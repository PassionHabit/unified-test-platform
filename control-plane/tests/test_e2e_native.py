"""M1 端到端（真实链路）：提交 → 调度分配 → Native 真实子进程执行 →
日志分片上传（真 S3 协议）→ 产物上传 → junit 解析 → COMPLETED/outcome。

不做任何 Mock：HTTP 是真实 uvicorn，S3 是真实 moto server，执行是真实子进程。
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.usefixtures("e2e_stack")

JUNIT_PASS = """<?xml version="1.0"?>
<testsuite name="demo" tests="2" failures="1" skipped="0">
  <testcase name="test_ok" classname="demo.Tests" time="0.01"/>
  <testcase name="test_bad" classname="demo.Tests" time="0.02">
    <failure message="assert 1 == 2">AssertionError</failure>
  </testcase>
</testsuite>"""

# Demo 命令：真实 python 子进程；写 junit 报告 + 输出日志（用绝对路径解释器，避免 PATH 差异）
import sys as _sys

DEMO_ARGV = [
    _sys.executable, "-c",
    "import os, sys\n"
    "print('hello-from-e2e-test')\n"
    "print('to-stderr-line', file=sys.stderr)\n"
    "d = os.environ['UTP_ARTIFACTS_DIR']\n"
    "open(os.path.join(d, 'junit.xml'), 'w').write(%r)\n" % JUNIT_PASS,
]

SLEEP_ARGV = [_sys.executable, "-c", "import time; print('sleeping'); time.sleep(300)"]


@pytest.fixture(scope="module")
def api(e2e_stack):
    base = e2e_stack["api"]
    client = httpx.Client(trust_env=False, timeout=60, base_url=base)
    yield client
    client.close()


@pytest.fixture(scope="module")
def demo_project(api):
    api.post("/api/v1/projects", json={"name": "e2e-native", "source_type": "git", "repository_ref": "demo"})
    r = api.post(
        "/api/v1/projects/e2e-native/profiles",
        json={
            "name": "default",
            "runtime_image_ref": "local-native",
            "argv": DEMO_ARGV,
            "artifacts": {"report_type": "pytest"},
        },
    )
    assert r.status_code in (201, 409), r.text
    return "e2e-native"


def _agent_poll(api, agent_id="e2e-agent", running=None):
    r = api.post(
        "/agent/v1/poll",
        json={"agent_id": agent_id, "node_type": "native", "labels": [],
              "cpu_total": 8, "memory_mb_total": 16384, "running_attempt_ids": running or []},
    )
    r.raise_for_status()
    return r.json()


def _wait_terminal(api, exec_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = api.get(f"/api/v1/executions/{exec_id}").json()
        if body["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return body
        time.sleep(1)
    raise AssertionError(f"execution {exec_id} not terminal: {body}")


class TestNativeE2E:
    def test_full_loop(self, api, demo_project):
        # 1. 提交
        r = api.post(
            "/api/v1/executions",
            json={"project_id": "e2e-native", "source_revision": "main",
                  "caller": {"type": "human"}},
        )
        assert r.status_code == 202, r.text
        exec_id = r.json()["id"]

        # 2. Agent 领取（真实分配，含 spec/死线）
        poll = _agent_poll(api)
        assert len(poll["assignments"]) == 1, poll
        spec = poll["assignments"][0]
        assert spec["execution_id"] == str(exec_id)
        assert spec["deadline_at"] is not None

        # 3. 真实执行（AttemptRunner：native 子进程 + 日志分片 + 产物上传）
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
        from utp_agent.attempt import AttemptRunner
        from utp_agent.client import ControlPlaneClient
        from utp_shared.agent_protocol import AttemptSpec

        cp_client = ControlPlaneClient(base_url=str(api.base_url).rstrip("/"))
        runner = AttemptRunner(AttemptSpec.model_validate(spec), cp_client, node_mode="native")
        runner.run()  # 同步跑完整个生命周期

        # 4. 终态 + 结论分离
        body = _wait_terminal(api, exec_id)
        assert body["status"] == "COMPLETED", body
        assert body["outcome"] == "FAILED"  # junit 里 1 个失败

        # 5. 日志（真 S3 读回）
        logs = api.get(f"/api/v1/executions/{exec_id}/logs", params={"stream": "stdout"})
        assert logs.status_code == 200
        assert "hello-from-e2e-test" in logs.text
        err_logs = api.get(f"/api/v1/executions/{exec_id}/logs", params={"stream": "stderr"})
        assert "to-stderr-line" in err_logs.text

        # 6. 产物清单 + 下载（预签名）
        arts = api.get(f"/api/v1/executions/{exec_id}/artifacts").json()
        paths = [a["path"] for a in arts]
        assert "junit.xml" in paths
        junit_art = next(a for a in arts if a["path"] == "junit.xml")
        assert junit_art["size"] > 0 and junit_art["sha256"]
        with_url = api.get(
            f"/api/v1/executions/{exec_id}/artifacts", params={"download": "true"}
        ).json()
        dl = next(a for a in with_url if a["path"] == "junit.xml")["download_url"]
        content = httpx.get(dl, trust_env=False, timeout=30)
        assert content.status_code == 200 and b"test_bad" in content.content

        # 7. 结果摘要
        result = api.get(f"/api/v1/executions/{exec_id}/result").json()
        assert result["total"] == 2 and result["failed"] == 1 and result["passed"] == 1
        assert any(f["name"] == "test_bad" for f in result["failures"])

        # 8. 事件流
        events = api.get(f"/api/v1/executions/{exec_id}/events").json()
        types = [e["event_type"] for e in events]
        assert "execution.finalized" in types
        assert "execution.result_summary_parsed" in types

        # 9. execution-context.json 永不收集
        assert "execution-context.json" not in paths

    def test_cancel_running_execution(self, api, demo_project):
        import sys
        import threading

        # longrun profile：sleep 300s，用于取消路径
        api.post("/api/v1/projects/e2e-native/profiles", json={
            "name": "longrun", "runtime_image_ref": "local-native",
            "argv": SLEEP_ARGV,
        })
        r2 = api.post(
            "/api/v1/executions",
            json={"project_id": "e2e-native", "profile": "longrun",
                  "source_revision": "main", "caller": {"type": "human"}},
        )
        exec_id = r2.json()["id"]
        poll = _agent_poll(api)
        spec = poll["assignments"][0]

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
        from utp_agent.attempt import AttemptRunner
        from utp_agent.client import ControlPlaneClient
        from utp_shared.agent_protocol import AttemptSpec

        cp_client = ControlPlaneClient(base_url=str(api.base_url).rstrip("/"))
        runner = AttemptRunner(AttemptSpec.model_validate(spec), cp_client, node_mode="native")
        t = threading.Thread(target=runner.run, daemon=True)
        t.start()

        # 等 RUNNING
        deadline = time.time() + 30
        while time.time() < deadline:
            body = api.get(f"/api/v1/executions/{exec_id}").json()
            if body["status"] == "RUNNING":
                break
            time.sleep(0.5)
        assert body["status"] == "RUNNING"

        # 取消 → poll 带回指令 → runner 停止
        api.post(f"/api/v1/executions/{exec_id}/cancel")
        poll = _agent_poll(api, running=[spec["attempt_id"]])
        assert poll["commands"], "cancel command should be delivered"
        assert poll["commands"][0]["cancel"]["attempt_id"] == spec["attempt_id"]
        runner.cancel_event.set()
        t.join(timeout=30)

        body = _wait_terminal(api, exec_id)
        assert body["status"] == "CANCELLED"
        assert body["failure_reason"] == "CANCELLED_BY_USER"

    def test_duplicate_poll_same_agent_no_double_assign(self, api, demo_project):
        """两次提交 + 单节点单槽：一次 poll 只领一个，第二次 poll 领第二个。"""
        api.post("/api/v1/executions", json={"project_id": "e2e-native", "source_revision": "m", "caller": {"type": "human"}})
        api.post("/api/v1/executions", json={"project_id": "e2e-native", "source_revision": "m", "caller": {"type": "human"}})
        first = _agent_poll(api, agent_id="serial-agent")
        ids1 = [a["attempt_id"] for a in first["assignments"]]
        assert len(ids1) == 1  # native 单槽
        second = _agent_poll(api, agent_id="serial-agent", running=ids1)
        ids2 = [a["attempt_id"] for a in second["assignments"]]
        assert len(ids2) == 0  # 槽占满，不重复分配
