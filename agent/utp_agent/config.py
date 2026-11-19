"""Agent 配置。"""
from __future__ import annotations

import socket
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UTP_", extra="ignore")

    control_url: str = "http://localhost:8000"
    agent_name: str = socket.gethostname()
    node_type: str = "docker"  # docker | native
    labels: str = ""  # 逗号分隔
    agent_version: str = "0.1.0"
    poll_timeout_s: float = 35.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
