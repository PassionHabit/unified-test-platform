from fastapi import APIRouter

from . import admin, executions, nodes, ops, projects, services

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(executions.router)
api_router.include_router(projects.router)
api_router.include_router(nodes.router)
api_router.include_router(services.router)
api_router.include_router(ops.router)
api_router.include_router(admin.router)
