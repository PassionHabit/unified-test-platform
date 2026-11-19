"""应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api.agent.v1 import router as agent_router
from .api.v1 import api_router
from .db import get_sessionmaker
from .models import Department


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 确保默认部门存在（幂等；schema 由 alembic 管理）
    session = get_sessionmaker()()
    try:
        exists = session.execute(
            select(Department).where(Department.name == "default")
        ).scalar_one_or_none()
        if exists is None:
            session.add(Department(name="default", max_concurrent=20))
            session.commit()
    except Exception:
        # 健康检查/文档场景下数据库未就绪不应阻止应用启动
        pass
    finally:
        session.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Unified Test Platform Control Plane",
        version="0.1.0",
        description="统一自动化测试执行平台 · 控制面（M0 骨架）",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # M0 开发环境；M4 收敛为控制台域名
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    app.include_router(agent_router)

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict:
        return {"status": "ok", "milestone": "M0"}

    return app


app = create_app()
