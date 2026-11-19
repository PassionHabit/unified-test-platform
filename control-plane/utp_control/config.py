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
    s3_region: str = "us-east-1"
    # Agent 长轮询返回前最长挂起秒数（M0 立即返回）
    agent_long_poll_s: int = 30
    default_max_timeout_s: int = 172800  # 48h
    # 对账器（M2）：周期、心跳超时、LOST 收敛窗口
    reconcile_interval_s: int = 15
    heartbeat_stale_s: int = 90
    lost_grace_s: int = 3600
    reconcile_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
