"""测试夹具：对 Alembic 迁移出的真实库跑 API 契约测试（SQLite）。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

CP_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def migrated_db_url(tmp_path_factory):
    """先设 DATABASE_URL 再导入应用模块，保证惰性引擎读到测试库。"""
    url = f"sqlite:///{tmp_path_factory.mktemp('db') / 'test.db'}"
    os.environ["DATABASE_URL"] = url

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(CP_DIR / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield url
    os.environ.pop("DATABASE_URL", None)


@pytest.fixture(scope="session")
def client(migrated_db_url):
    from fastapi.testclient import TestClient

    from utp_control.config import get_settings
    from utp_control.db import get_engine, get_sessionmaker
    from utp_control.main import app

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    with TestClient(app) as c:  # lifespan 会补种默认部门
        yield c


@pytest.fixture(scope="session")
def seeded_project(client):
    """创建带 default profile 的测试项目（幂等，session 级共享）。"""
    resp = client.post(
        "/api/v1/projects",
        json={"name": "robot-web-smoke", "source_type": "git", "repository_ref": "web-tests"},
    )
    assert resp.status_code in (201, 409), resp.text
    resp = client.post(
        "/api/v1/projects/robot-web-smoke/profiles",
        json={
            "name": "default",
            "runtime_image_ref": "test-browser:stable",
            "argv": ["robot", "--outputdir", "/artifacts", "tests/"],
        },
    )
    assert resp.status_code in (201, 409), resp.text
    return "robot-web-smoke"


def submit(client, project="robot-web-smoke", headers=None, **overrides):
    payload = {
        "project_id": project,
        "source_revision": "main",
        "parameters": {"environment": {"base_url": "https://test.example.invalid"}},
        "caller": {"type": "pipeline", "run_ref": "pipeline-123"},
    }
    payload.update(overrides)
    return client.post("/api/v1/executions", json=payload, headers=headers)
