"""控制面客户端：长轮询与上报。"""
from __future__ import annotations

from typing import List, Optional

import httpx

from utp_shared.agent_protocol import (
    AttemptStatusReport,
    LogManifestUpdate,
    PollRequest,
    PollResponse,
)

from .config import get_settings


class ControlPlaneClient:
    def __init__(self, base_url: Optional[str] = None, client: Optional[httpx.Client] = None):
        settings = get_settings()
        self.base_url = (base_url or settings.control_url).rstrip("/")
        # trust_env=False：基础设施组件直连控制面，不受用户代理环境变量影响
        self._client = client or httpx.Client(
            timeout=settings.poll_timeout_s + 5, trust_env=False
        )

    def poll(
        self,
        agent_id: str,
        node_type: str,
        labels: List[str],
        cpu_total: int = 0,
        memory_mb_total: int = 0,
        running_attempt_ids: Optional[List[str]] = None,
    ) -> PollResponse:
        body = PollRequest(
            agent_id=agent_id,
            node_type=node_type,
            labels=labels,
            cpu_total=cpu_total,
            memory_mb_total=memory_mb_total,
            agent_version=get_settings().agent_version,
            running_attempt_ids=running_attempt_ids or [],
        )
        resp = self._client.post(f"{self.base_url}/agent/v1/poll", json=body.model_dump(mode="json"))
        resp.raise_for_status()
        return PollResponse.model_validate(resp.json())

    def report_status(self, report: AttemptStatusReport) -> None:
        resp = self._client.post(
            f"{self.base_url}/agent/v1/attempts/{report.attempt_id}/status",
            json=report.model_dump(mode="json"),
        )
        resp.raise_for_status()

    def report_log_manifest(self, update: LogManifestUpdate) -> None:
        resp = self._client.post(
            f"{self.base_url}/agent/v1/attempts/{update.attempt_id}/log-manifest",
            json=update.model_dump(mode="json"),
        )
        resp.raise_for_status()
