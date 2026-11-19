"""执行 API 契约测试：幂等提交、查询、列表、取消。"""
from __future__ import annotations

from conftest import submit


class TestSubmit:
    def test_submit_returns_202_queued(self, client, seeded_project):
        resp = submit(client)
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "QUEUED"
        assert body["outcome"] == "UNKNOWN"
        assert body["priority"] == 0
        assert f"/api/v1/executions/{body['id']}" == resp.headers["Location"]

    def test_idempotent_replay_same_key_same_caller(self, client, seeded_project):
        headers = {"Idempotency-Key": "key-001"}
        first = submit(client, headers=headers)
        second = submit(client, headers=headers)
        assert first.status_code == 202
        assert second.status_code == 200
        assert second.headers.get("Idempotency-Replayed") == "true"
        assert first.json()["id"] == second.json()["id"]

    def test_different_key_creates_new(self, client, seeded_project):
        a = submit(client, headers={"Idempotency-Key": "key-a"})
        b = submit(client, headers={"Idempotency-Key": "key-b"})
        assert a.json()["id"] != b.json()["id"]

    def test_same_key_different_caller_scope_not_replayed(self, client, seeded_project):
        headers = {"Idempotency-Key": "key-scope"}
        a = submit(client, headers=headers)
        b = submit(client, headers=headers, caller={"type": "human"})
        assert a.json()["id"] != b.json()["id"]

    def test_unknown_project_404(self, client, seeded_project):
        resp = submit(client, project="no-such-project")
        assert resp.status_code == 404

    def test_unknown_profile_404(self, client, seeded_project):
        resp = submit(client, profile="missing")
        assert resp.status_code == 404

    def test_priority_out_of_range_422(self, client, seeded_project):
        assert submit(client, priority=10).status_code == 422
        assert submit(client, priority=-1).status_code == 422

    def test_timeout_over_limit_422(self, client, seeded_project):
        assert submit(client, timeout_seconds=200000).status_code == 422


class TestGetAndList:
    def test_get_by_id(self, client, seeded_project):
        exec_id = submit(client).json()["id"]
        resp = client.get(f"/api/v1/executions/{exec_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == exec_id
        assert resp.json()["status"] == "QUEUED"

    def test_get_missing_404(self, client, seeded_project):
        assert client.get("/api/v1/executions/99999").status_code == 404

    def test_list_filter_by_project_and_status(self, client, seeded_project):
        submit(client)
        submit(client)
        resp = client.get("/api/v1/executions", params={"project": "robot-web-smoke", "status": "QUEUED"})
        assert resp.status_code == 200
        assert len(resp.json()) >= 2
        assert all(e["status"] == "QUEUED" for e in resp.json())

    def test_list_unknown_status_422(self, client, seeded_project):
        assert client.get("/api/v1/executions", params={"status": "BOGUS"}).status_code == 422


class TestCancel:
    def test_cancel_queued_immediate(self, client, seeded_project):
        exec_id = submit(client).json()["id"]
        resp = client.post(f"/api/v1/executions/{exec_id}/cancel")
        assert resp.status_code == 202
        assert resp.json()["status"] == "CANCELLED"
        assert resp.json()["cancel_requested"] is True

        got = client.get(f"/api/v1/executions/{exec_id}").json()
        assert got["status"] == "CANCELLED"
        assert got["failure_reason"] == "CANCELLED_BY_USER"
        assert got["ended_at"] is not None

    def test_cancel_twice_409(self, client, seeded_project):
        exec_id = submit(client).json()["id"]
        assert client.post(f"/api/v1/executions/{exec_id}/cancel").status_code == 202
        assert client.post(f"/api/v1/executions/{exec_id}/cancel").status_code == 409

    def test_cancel_missing_404(self, client, seeded_project):
        assert client.post("/api/v1/executions/99999/cancel").status_code == 404


class TestDeferredEndpoints:
    def test_events_501(self, client, seeded_project):
        exec_id = submit(client).json()["id"]
        assert client.get(f"/api/v1/executions/{exec_id}/events").status_code == 501

    def test_logs_and_artifacts_501(self, client, seeded_project):
        exec_id = submit(client).json()["id"]
        assert client.get(f"/api/v1/executions/{exec_id}/logs").status_code == 501
        assert client.get(f"/api/v1/executions/{exec_id}/artifacts").status_code == 501
