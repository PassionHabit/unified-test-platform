"""API 请求/响应模型（V2.1 §11）。"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CallerInfo(BaseModel):
    type: str = Field(default="human", pattern="^(pipeline|human)$")
    run_ref: Optional[str] = Field(default=None, max_length=200)


class ExecutionCreate(BaseModel):
    project_id: str = Field(min_length=1, max_length=100, description="项目名")
    profile: Optional[str] = Field(default=None, max_length=100, description="Profile 名，缺省 default")
    parameters: Dict = Field(default_factory=dict)
    source_revision: str = Field(min_length=1, max_length=200)
    priority: int = Field(default=0, ge=0, le=9)
    timeout_seconds: Optional[int] = Field(default=None, le=172800)
    caller: Optional[CallerInfo] = None
    callback_ref: Optional[str] = Field(default=None, max_length=200)


class ExecutionOut(BaseModel):
    id: int
    project_id: int
    profile_name: str
    profile_revision: Optional[int] = None
    priority: int
    source_revision: str
    status: str
    outcome: str
    failure_reason: str
    timeout_seconds: int
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    cancel_requested_at: Optional[datetime] = None
    pipeline_run_ref: Optional[str] = None

    model_config = {"from_attributes": True}


class CancelOut(BaseModel):
    id: int
    status: str
    cancel_requested: bool


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    department_id: Optional[int] = None
    source_type: str = Field(pattern="^(git|svn)$")
    repository_ref: str = Field(min_length=1, max_length=500)
    owner: Optional[str] = Field(default=None, max_length=100)


class ProjectOut(BaseModel):
    id: int
    name: str
    department_id: int
    source_type: str
    repository_ref: str
    owner: Optional[str] = None
    status: str

    model_config = {"from_attributes": True}


class ProfileCreate(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=100)
    runtime_image_ref: str = Field(min_length=1, max_length=500)
    argv: List[str] = Field(min_length=1)
    prepare_argv: Optional[List[str]] = None
    prepare_timeout_s: int = Field(default=600, ge=1, le=3600)
    parameter_schema: Dict = Field(default_factory=dict)
    resources: Dict = Field(default_factory=dict)
    artifacts: Dict = Field(default_factory=dict)
    service_bindings: Optional[Dict] = None
    timeout_default: int = Field(default=172800, ge=1, le=172800)


class ProfileOut(BaseModel):
    id: int
    project_id: int
    name: str
    revision: int
    runtime_image_ref: str
    timeout_default: int
    enabled: bool

    model_config = {"from_attributes": True}
