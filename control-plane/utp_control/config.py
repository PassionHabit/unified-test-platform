"""控制面配置（环境变量优先）。"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    database_url: str = "sqlite:///./utp.db"
    # 对象存储（M0 仅透传配置，M1 日志/产物上传启用）
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "utp"
    # Agent 长轮询返回前最长挂起秒数（M0 立即返回）
    agent_long_poll_s: int = 30
    default_max_timeout_s: int = 172800  # 48h


@lru_cache
def get_settings() -> Settings:
    return Settings()
