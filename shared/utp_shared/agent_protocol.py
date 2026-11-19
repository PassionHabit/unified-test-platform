"""Agent 协议消息（V2.1 §8）。

Agent→控制面全部为 Agent 发起（长轮询/上报）；start/cancel 为下发语义，
经 PollResponse 的 assignments / commands 传递。spec 一经下发不可变。
兼容 Python 3.9：类型注解使用 Optional。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .states import AttemptStatus


class PrepareSpec(BaseModel):
    argv: List[str] = Field(min_length=1)
    timeout_s: int = Field(default=600, ge=1, le=3600)


class ResourceSpec(BaseModel):
    cpu: float = Field(default=2, gt=0)
    memory_mb: int = Field(default=4096, gt=0)
    shm_mb: int = Field(default=1024, ge=0)


class AttemptSpec(BaseModel):
    """随 assignment 下发的不可变执行规格。"""

    attempt_id: str
    execution_id: str
    image: str
    image_digest: Optional[str] = None
    argv: List[str] = Field(min_length=1)
    env: Dict[str, str] = Field(default_factory=dict)
    prepare: Optional[PrepareSpec] = None
    resources: ResourceSpec = ResourceSpec()
    workspace_dir: str = "/workspace"
    artifacts_dir: str = "/artifacts"
    deadline_at: Optional[datetime] = None

    model_config = {"extra": "forbid"}


class CancelCommand(BaseModel):
    attempt_id: str
    reason: str = "user_request"
    grace_s: int = Field(default=30, ge=0, le=600)


class ControlCommand(BaseModel):
    cancel: Optional[CancelCommand] = None

    model_config = {"extra": "forbid"}


class PollRequest(BaseModel):
    """Agent 长轮询请求，兼作心跳（控制面据此刷新 worker_node）。"""

    agent_id: str = Field(min_length=1, max_length=100)
    node_type: str = Field(default="docker", pattern="^(docker|native)$")
    labels: List[str] = Field(default_factory=list)
    cpu_total: int = Field(default=0, ge=0)
    memory_mb_total: int = Field(default=0, ge=0)
    agent_version: str = "0.1.0"
    running_attempt_ids: List[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class PollResponse(BaseModel):
    assignments: List[AttemptSpec] = Field(default_factory=list)
    commands: List[ControlCommand] = Field(default_factory=list)
    poll_after_s: int = Field(default=5, ge=1, le=60)

    model_config = {"extra": "ignore"}


class AttemptStatusReport(BaseModel):
    report_id: str
    attempt_id: str
    execution_id: str
    status: AttemptStatus
    exit_code: Optional[int] = None
    oom_killed: bool = False
    message: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    model_config = {"extra": "ignore"}


class LogChunkInfo(BaseModel):
    stream: str = Field(pattern="^(stdout|stderr)$")
    index: int = Field(ge=0)
    bytes: int = Field(ge=0)
    object_key: str


class LogManifestUpdate(BaseModel):
    attempt_id: str
    chunks: List[LogChunkInfo] = Field(default_factory=list)
    bytes_total: int = Field(default=0, ge=0)
    finalized: bool = False

    model_config = {"extra": "ignore"}
