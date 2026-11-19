"""项目 / Profile 管理 API 测试。"""
from __future__ import annotations


class TestProjects:
    def test_create_and_get(self, client):
        resp = client.post(
            "/api/v1/projects",
            json={"name": "pytest-unit", "source_type": "git", "repository_ref": "unit-tests", "owner": "alice"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "pytest-unit"
        assert body["status"] == "active"

        got = client.get("/api/v1/projects/pytest-unit")
        assert got.status_code == 200
        assert got.json()["id"] == body["id"]

    def test_duplicate_name_409(self, client):
        payload = {"name": "dup-project", "source_type": "git", "repository_ref": "r"}
        assert client.post("/api/v1/projects", json=payload).status_code == 201
        assert client.post("/api/v1/projects", json=payload).status_code == 409

    def test_invalid_name_422(self, client):
        payload = {"name": "Bad_Name!", "source_type": "git", "repository_ref": "r"}
        assert client.post("/api/v1/projects", json=payload).status_code == 422

    def test_invalid_source_type_422(self, client):
        payload = {"name": "valid-name", "source_type": "perforce", "repository_ref": "r"}
        assert client.post("/api/v1/projects", json=payload).status_code == 422

    def test_list(self, client):
        resp = client.get("/api/v1/projects")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestProfiles:
    def test_create_and_list(self, client):
        client.post("/api/v1/projects", json={"name": "jmeter-load", "source_type": "git", "repository_ref": "load"})
        resp = client.post(
            "/api/v1/projects/jmeter-load/profiles",
            json={
                "name": "default",
                "runtime_image_ref": "jmeter:5.6",
                "argv": ["jmeter", "-n", "-t", "plan.jmx"],
                "prepare_argv": ["pip", "install", "-r", "requirements.txt"],
                "timeout_default": 7200,
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["revision"] == 1

        listed = client.get("/api/v1/projects/jmeter-load/profiles")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    def test_duplicate_profile_409(self, client):
        client.post("/api/v1/projects", json={"name": "profile-dup", "source_type": "svn", "repository_ref": "s"})
        payload = {"runtime_image_ref": "python:3.12", "argv": ["pytest", "tests/"]}
        assert client.post("/api/v1/projects/profile-dup/profiles", json=payload).status_code == 201
        assert client.post("/api/v1/projects/profile-dup/profiles", json=payload).status_code == 409

    def test_profile_on_missing_project_404(self, client):
        payload = {"runtime_image_ref": "python:3.12", "argv": ["true"]}
        assert client.post("/api/v1/projects/ghost/profiles", json=payload).status_code == 404


class TestAgentAndNodes:
    def test_agent_poll_registers_node(self, client):
        resp = client.post(
            "/agent/v1/poll",
            json={
                "agent_id": "agent-smoke-1",
                "node_type": "docker",
                "labels": ["web-test"],
                "cpu_total": 16,
                "memory_mb_total": 32768,
                "agent_version": "0.1.0",
                "unknown_extra_field": "ignored",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["poll_after_s"] >= 1

        nodes = client.get("/api/v1/nodes").json()
        mine = [n for n in nodes if n["agent_id"] == "agent-smoke-1"]
        assert len(mine) == 1
        assert mine[0]["labels"] == ["web-test"]

    def test_zero_capacity_node_claims_nothing(self, client):
        resp = client.post(
            "/agent/v1/poll",
            json={"agent_id": "agent-zero-cap", "node_type": "docker",
                  "cpu_total": 0, "memory_mb_total": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["assignments"] == []

    def test_agent_poll_heartbeat_refresh(self, client):
        for _ in range(2):
            assert client.post("/agent/v1/poll", json={"agent_id": "agent-hb"}).status_code == 200
        nodes = [n for n in client.get("/api/v1/nodes").json() if n["agent_id"] == "agent-hb"]
        assert len(nodes) == 1  # 幂等注册，不重复建节点

    def test_attempt_status_unknown_404(self, client):
        resp = client.post(
            "/agent/v1/attempts/999999/status",
            json={
                "report_id": "r-1",
                "attempt_id": "999999",
                "execution_id": "1",
                "status": "RUNNING",
            },
        )
        assert resp.status_code == 404
