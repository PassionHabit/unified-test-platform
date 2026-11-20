"""M4 测试：令牌认证与部门隔离、outbox 回调、/metrics、镜像库。"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from conftest import submit


def _db():
    from utp_control.db import get_sessionmaker

    return get_sessionmaker()()


class TestAuth:
    def test_token_issue_and_auth_disabled_by_default(self, client):
        """auth 关闭（默认）：无令牌也放行（本地开发模式）。"""
        r = client.post("/api/v1/tokens", json={"name": "t1", "role": "human"})
        assert r.status_code == 201, r.text
        assert r.json()["token"].startswith("utp_")
        assert client.get("/api/v1/tokens").status_code == 200

    def test_auth_enabled_rejects_without_token(self, client, monkeypatch):
        from utp_control import auth as auth_mod
        from utp_control.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("AUTH_ENABLED", "true")

        # require_principal 逻辑验证：auth 开启时无 Bearer 头 → 401
        from fastapi import HTTPException

        class FakeRequest:
            headers = {}

        try:
            auth_mod.require_principal(FakeRequest())
            raised = False
        except HTTPException as e:
            raised = e.status_code == 401
        assert raised
        get_settings.cache_clear()
        monkeypatch.delenv("AUTH_ENABLED", raising=False)

    def test_department_isolation_logic(self, client):
        from utp_control.auth import Principal, check_project_access
        from fastapi import HTTPException

        admin = Principal(role="admin", department_id=None)
        check_project_access(admin, 999)  # admin 全放行

        dept_a = Principal(role="human", department_id=1)
        check_project_access(dept_a, 1)  # 本部门放行
        try:
            check_project_access(dept_a, 2)
            raise AssertionError("cross-department should be denied")
        except HTTPException as e:
            assert e.status_code == 403


class TestOutbox:
    def test_callback_delivered_to_allowlisted_target(self, client, seeded_project):
        import threading

        received = []

        from fastapi import FastAPI
        import uvicorn

        app = FastAPI()

        @app.get("/ping")
        def ping():
            return {"ok": True}

        @app.post("/cb")
        def cb(body: dict):
            received.append(body)
            return {"ok": True}

        import socket

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        deadline = time.time() + 10
        import httpx

        while time.time() < deadline:
            try:
                httpx.get(f"http://127.0.0.1:{port}/ping", trust_env=False, timeout=1)
                break
            except Exception:
                time.sleep(0.2)

        # 白名单 + 提交（带 callback_ref）→ 立即取消触发 finalize
        from utp_control.config import get_settings

        get_settings.cache_clear()
        import os

        os.environ["CALLBACK_ALLOWLIST"] = f"http://127.0.0.1:{port}"
        try:
            resp = submit(client, callback_ref=f"http://127.0.0.1:{port}/cb")
            eid = resp.json()["id"]
            client.post(f"/api/v1/executions/{eid}/cancel")

            from utp_control.db import get_sessionmaker
            from utp_control.outbox import deliver_pending

            deadline = time.time() + 10
            while time.time() < deadline and not received:
                s2 = get_sessionmaker()()
                try:
                    deliver_pending(s2)
                finally:
                    s2.close()
                time.sleep(0.5)
            assert received, "回调未投递"
            assert received[0]["event_type"] == "execution.finalized"
            assert received[0]["execution_id"] == eid
            assert received[0]["status"] == "CANCELLED"
        finally:
            os.environ.pop("CALLBACK_ALLOWLIST", None)
            get_settings.cache_clear()

    def test_non_allowlisted_target_blocked(self, client, seeded_project):
        import os

        from utp_control.config import get_settings

        get_settings.cache_clear()
        os.environ["CALLBACK_ALLOWLIST"] = "http://10.255.255.1:1/"
        try:
            resp = submit(client, callback_ref="http://evil.example.invalid/hook")
            eid = resp.json()["id"]
            client.post(f"/api/v1/executions/{eid}/cancel")  # QUEUED 快速路径也入队回调

            from utp_control.db import get_sessionmaker
            from utp_control.models import CallbackDelivery
            from utp_control.outbox import deliver_pending

            s2 = get_sessionmaker()()
            try:
                deliver_pending(s2)
                row = s2.query(CallbackDelivery).filter(
                    CallbackDelivery.execution_id == eid).first()
                assert row is not None and row.state == "blocked"
            finally:
                s2.close()
        finally:
            os.environ.pop("CALLBACK_ALLOWLIST", None)
            get_settings.cache_clear()


class TestMetricsAndImages:
    def test_metrics_exposition(self, client, seeded_project):
        submit(client)
        r = client.get("/api/v1/metrics")
        assert r.status_code == 200
        text = r.text
        assert "utp_executions" in text and 'status="QUEUED"' in text
        assert "# TYPE utp_executions gauge" in text

    def test_image_registry_crud(self, client):
        r = client.post("/api/v1/images", json={
            "name": "robot-chrome", "tag": "stable", "source": "official",
            "ref_uri": "harbor.internal/utp/robot-chrome:stable"})
        assert r.status_code == 201, r.text
        dup = client.post("/api/v1/images", json={
            "name": "robot-chrome", "tag": "stable", "source": "official",
            "ref_uri": "x"})
        assert dup.status_code == 409
        listed = client.get("/api/v1/images").json()
        assert any(i["name"] == "robot-chrome" for i in listed)
