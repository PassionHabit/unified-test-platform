"""测试夹具：对 Alembic 迁移出的真实库跑 API 契约测试（SQLite）。"""
from __future__ import annotations

import os
import subprocess
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
    cfg.set_main_option("script_location", str(CP_DIR / "alembic"))
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


# ---------- M1 真实 E2E 栈：真 HTTP（uvicorn 线程）+ 真 S3（moto server 子进程） ----------

def _free_port() -> int:
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port: int, timeout: float = 20.0) -> None:
    import socket
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"port {port} not ready")


@pytest.fixture(scope="module")
def e2e_stack():
    """独立数据库 + 真实 HTTP（uvicorn 线程）+ 真实 S3（moto 子进程）。

    module 级：每个 E2E 模块独立一套栈，用完即还原环境与缓存，
    不与契约测试（session 库）互相污染。
    """
    import tempfile
    import threading

    tmp = tempfile.mkdtemp(prefix="utp-e2e-")
    e2e_db = f"sqlite:///{tmp}/e2e.db"
    previous_db = os.environ.get("DATABASE_URL")
    s3_previous = {k: os.environ.get(k) for k in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET")}

    # 先切环境再迁移：env.py 里环境变量优先于 ini 的 url，
    # 否则迁移会打到前一个模块留下的库上
    os.environ["DATABASE_URL"] = e2e_db

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(CP_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CP_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", e2e_db)
    command.upgrade(cfg, "head")

    s3_port = _free_port()
    moto_bin = str(CP_DIR.parent / ".venv" / "bin" / "moto_server")
    moto_proc = subprocess.Popen(
        [moto_bin, "-p", str(s3_port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def _restore():
        moto_proc.terminate()
        moto_proc.wait(timeout=10)
        for k, v in s3_previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if previous_db is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_db
        from utp_control import storage as storage_mod
        from utp_control.config import get_settings
        from utp_control.db import get_engine, get_sessionmaker

        get_settings.cache_clear()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
        storage_mod.get_storage.cache_clear()

    try:
        _wait_port(s3_port)
        os.environ["S3_ENDPOINT"] = f"http://127.0.0.1:{s3_port}"
        os.environ["S3_ACCESS_KEY"] = "test"
        os.environ["S3_SECRET_KEY"] = "test"
        os.environ["S3_BUCKET"] = "utp-e2e"

        from utp_control import storage as storage_mod
        from utp_control.config import get_settings
        from utp_control.db import get_engine, get_sessionmaker
        from utp_control.main import app

        get_settings.cache_clear()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
        storage_mod.get_storage.cache_clear()
        storage_mod.get_storage().ensure_bucket()

        api_port = _free_port()
        import uvicorn

        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning")
        )
        threading.Thread(target=server.run, daemon=True).start()
        _wait_port(api_port)
        yield {"api": f"http://127.0.0.1:{api_port}"}
    finally:
        _restore()
