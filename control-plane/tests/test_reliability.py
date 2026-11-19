"""M2 可靠性测试：部门公平/配额、心跳对账（RECONCILING 双向）、mark-lost、排水。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import submit


def _db_session():
    from utp_control.db import get_sessionmaker

    return get_sessionmaker()()


def _create_dept_project(client, dept_name, project_name, quota=20):
    from utp_control.models import Department, Project

    with _db_session() as s:
        dept = s.execute(select(Department).where(Department.name == dept_name)).scalar_one_or_none()
        if dept is None:
            s.add(Department(name=dept_name, max_concurrent=quota))
            s.commit()
            dept = s.execute(select(Department).where(Department.name == dept_name)).scalar_one()
        dept_id = dept.id
    resp = client.post(
        "/api/v1/projects",
        json={"name": project_name, "department_id": dept_id, "source_type": "git", "repository_ref": "r"},
    )
    assert resp.status_code == 201, resp.text
    client.post(
        f"/api/v1/projects/{project_name}/profiles",
        json={"runtime_image_ref": "python:3.12", "argv": ["true"]},
    )
    return dept_id


from sqlalchemy import select  # noqa: E402


def _poll_claim(client, agent_id, cpu=2, running=None):
    r = client.post(
        "/agent/v1/poll",
        json={"agent_id": agent_id, "node_type": "docker", "labels": ["fair"],
              "cpu_total": cpu, "memory_mb_total": 16384, "running_attempt_ids": running or []},
    )
    assert r.status_code == 200, r.text
    return r.json()["assignments"]


class TestFairnessAndQuota:
    def test_department_fairness_round_robin(self, client):
        """alpha 有多个排队任务，beta 只有一个：调度必须轮转服务，不能让 alpha 独占。"""
        _create_dept_project(client, "dept-alpha", "alpha-proj")
        _create_dept_project(client, "dept-beta", "beta-proj")
        for _ in range(3):
            submit(client, project="alpha-proj")
        submit(client, project="beta-proj")

        first = _poll_claim(client, "fair-agent-1")
        assert len(first) == 1
        # 第二次领取必须轮到另一个部门（先被服务的部门时间戳已推进）
        second = _poll_claim(client, "fair-agent-2")
        assert len(second) == 1
        with _db_session() as s:
            from utp_control.models import Execution, Project

            names = []
            for batch in (first, second):
                ex = s.get(Execution, int(batch[0]["execution_id"]))
                names.append(s.get(Project, ex.project_id).name)
            assert names[0] != names[1], f"公平轮转失效：连续领取了同一部门 {names}"
            assert set(names) == {"alpha-proj", "beta-proj"}

    def test_department_quota_blocks_new_claim(self, client):
        """部门配额满后，该部门新任务不再被领取，其他部门不受影响。"""
        _create_dept_project(client, "dept-quota", "quota-proj", quota=1)
        _create_dept_project(client, "dept-free", "free-proj", quota=99)

        submit(client, project="quota-proj")
        got = _poll_claim(client, "quota-agent-1")
        assert len(got) == 1
        # 推进到 RUNNING（占住配额）：CREATED → STARTING → RUNNING
        eid = got[0]["execution_id"]
        aid = got[0]["attempt_id"]
        client.post(f"/agent/v1/attempts/{aid}/status", json={
            "report_id": "r1", "attempt_id": aid, "execution_id": eid, "status": "STARTING"})
        client.post(f"/agent/v1/attempts/{aid}/status", json={
            "report_id": "r2", "attempt_id": aid, "execution_id": eid, "status": "RUNNING"})
        submit(client, project="quota-proj")  # 第二个任务（同部门，配额已满）
        submit(client, project="free-proj")   # 其他部门
        got2 = _poll_claim(client, "quota-agent-2")
        assert len(got2) == 1
        with _db_session() as s:
            from utp_control.models import Execution, Project

            ex = s.get(Execution, int(got2[0]["execution_id"]))
            proj = s.get(Project, ex.project_id)
            assert proj.name == "free-proj", "配额满的部门任务不应被领取"


class TestReconciler:
    """每个测试使用独立 agent（独立节点容量），避免测试间资源占用串扰。"""

    def _setup_running(self, client, agent):
        submit(client, project="robot-web-smoke")
        got = _poll_claim(client, agent)
        assert len(got) == 1, f"claim unexpected: {got}"
        spec = got[0]
        for status in ("STARTING", "RUNNING"):
            client.post(f"/agent/v1/attempts/{spec['attempt_id']}/status", json={
                "report_id": f"r-{status}", "attempt_id": spec["attempt_id"],
                "execution_id": spec["execution_id"], "status": status})
        return spec

    def _node_id(self, client, agent):
        nodes = client.get("/api/v1/nodes").json()
        return [n for n in nodes if n["agent_id"] == agent][0]["id"]

    def test_stale_heartbeat_then_recover(self, client, seeded_project):
        agent = "recon-hb"
        spec = self._setup_running(client, agent)

        # 心跳拨回 3 分钟前 → RECONCILING
        from utp_control.models import WorkerNode

        with _db_session() as s:
            node = s.execute(
                select(WorkerNode).where(WorkerNode.agent_id == agent)
            ).scalar_one()
            node.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=300)
            s.commit()

        r = client.post("/api/v1/admin/reconcile")
        assert r.status_code == 200
        assert r.json()["reconciling"] >= 1
        status = client.get(f"/api/v1/executions/{spec['execution_id']}").json()["status"]
        assert status == "RECONCILING"

        # 节点恢复心跳 → 回 RUNNING（不重复启动）
        client.post("/agent/v1/poll", json={"agent_id": agent, "cpu_total": 2})
        r2 = client.post("/api/v1/admin/reconcile")
        assert r2.json()["recovered"] >= 1
        status2 = client.get(f"/api/v1/executions/{spec['execution_id']}").json()["status"]
        assert status2 == "RUNNING"

    def test_mark_lost_requires_confirm_and_works(self, client, seeded_project):
        agent = "recon-mk"
        spec = self._setup_running(client, agent)
        eid = int(spec["execution_id"])
        bad = client.post(f"/api/v1/admin/executions/{eid}/mark-lost", headers={"X-Confirm": "wrong"})
        assert bad.status_code == 400
        ok = client.post(f"/api/v1/admin/executions/{eid}/mark-lost", headers={"X-Confirm": str(eid)})
        assert ok.status_code == 200
        body = client.get(f"/api/v1/executions/{eid}").json()
        assert body["status"] == "FAILED"
        assert body["failure_reason"] == "NODE_LOST"
        # mark-lost 必须释放预留：节点容量恢复后可继续领任务
        got = _poll_claim(client, agent)
        assert len(got) == 1
        # 终态后再次 mark-lost → 409
        again = client.post(f"/api/v1/admin/executions/{eid}/mark-lost", headers={"X-Confirm": str(eid)})
        assert again.status_code == 409

    def test_drain_blocks_and_restore(self, client, seeded_project):
        agent = "recon-dr1"
        submit(client)
        got = _poll_claim(client, agent)
        assert len(got) == 1  # 注册并占用槽位
        node_id = self._node_id(client, agent)

        assert client.post(f"/api/v1/nodes/{node_id}/drain", json={}).status_code == 200
        submit(client)  # 新任务
        got2 = _poll_claim(client, agent, running=[got[0]["attempt_id"]])
        assert got2 == [], "DRAINING 节点不应接新任务"
        assert client.post(f"/api/v1/nodes/{node_id}/restore", json={}).status_code == 200
        # 结束占位任务，释放槽位后再验证恢复接单
        for status in ("STARTING", "RUNNING", "EXITED"):
            payload = {
                "report_id": f"r-{status}", "attempt_id": got[0]["attempt_id"],
                "execution_id": got[0]["execution_id"], "status": status}
            if status == "EXITED":
                payload["exit_code"] = 0
            client.post(f"/agent/v1/attempts/{got[0]['attempt_id']}/status", json=payload)
        got3 = _poll_claim(client, agent)
        assert len(got3) == 1

    def test_drain_deadline_forces_cancel(self, client, seeded_project):
        agent = "recon-dr2"
        spec = self._setup_running(client, agent)
        node_id = self._node_id(client, agent)
        assert client.post(f"/api/v1/nodes/{node_id}/drain", json={"deadline_minutes": 1}).status_code == 200

        # 排水期限拨到过去，触发强制取消
        from utp_control.models import WorkerNode

        with _db_session() as s:
            node = s.get(WorkerNode, node_id)
            node.maintenance_deadline = datetime.now(timezone.utc) - timedelta(minutes=5)
            s.commit()

        r = client.post("/api/v1/admin/reconcile")
        assert r.json()["drain_cancelled"] >= 1
        body = client.get(f"/api/v1/executions/{spec['execution_id']}").json()
        assert body["status"] == "CANCELLED"
