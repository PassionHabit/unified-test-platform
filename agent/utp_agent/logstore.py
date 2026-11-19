"""日志分片管道：本地落盘 + 切片 + 预签名直传（V2.1 §12）。

切片条件：5MB 或 收到 flush()（执行结束/周期性）。分区期间本地全量保留，
恢复后续传；finalize 后标记 manifest 完成。
"""
from __future__ import annotations

import io
import os
import time
from typing import Optional

import httpx

from .client import ControlPlaneClient
from utp_shared.agent_protocol import LogChunkInfo, LogManifestUpdate

CHUNK_BYTES = 5 * 1024 * 1024
FLUSH_INTERVAL_S = 15


class ChunkedLogUploader:
    """单流（stdout/stderr）的切片上传器。"""

    def __init__(
        self,
        client: ControlPlaneClient,
        attempt_id: str,
        execution_id: str,
        stream: str,
        local_dir: str,
    ):
        self._client = client
        self.attempt_id = attempt_id
        self.execution_id = execution_id
        self.stream = stream
        self._prefix = f"executions/{execution_id}/attempts/{attempt_id}/{stream}"
        self._local_path = os.path.join(local_dir, f"{stream}.log")
        self._fh = open(self._local_path, "ab")
        self._buf = io.BytesIO()
        self._chunk_index = 0
        self._bytes_total = 0
        self._chunks: list = []
        self._last_flush = time.time()
        self._http = httpx.Client(trust_env=False, timeout=120)
        self._closed = False

    def write(self, data: bytes) -> None:
        if self._closed or not data:
            return
        self._fh.write(data)
        self._buf.write(data)
        self._bytes_total += len(data)
        if self._buf.tell() >= CHUNK_BYTES or time.time() - self._last_flush >= FLUSH_INTERVAL_S:
            self._maybe_flush()

    def _maybe_flush(self, force: bool = False) -> None:
        if self._buf.tell() == 0 and not force:
            return
        data = self._buf.getvalue()
        self._buf = io.BytesIO()
        self._last_flush = time.time()
        if not data:
            return
        key = f"{self._prefix}/{self._chunk_index:06d}.log"
        try:
            resp = self._client._request_json(
                "POST",
                f"/agent/v1/attempts/{self.attempt_id}/upload-urls",
                json={"keys": [key]},
            )
            url = resp["urls"][key]
            put = self._http.put(url, content=data)
            put.raise_for_status()
        except Exception:
            # 分区/失败：回写缓冲头部，本地保留，下次重试
            self._buf = io.BytesIO(data + self._buf.getvalue())
            return
        self._chunks.append(
            LogChunkInfo(stream=self.stream, index=self._chunk_index, bytes=len(data), object_key=key)
        )
        self._chunk_index += 1
        self._report(finalized=False)

    def _report(self, finalized: bool) -> None:
        try:
            self._client.report_log_manifest(
                LogManifestUpdate(
                    attempt_id=self.attempt_id,
                    chunks=self._chunks,
                    bytes_total=self._bytes_total,
                    finalized=finalized,
                )
            )
        except Exception:
            pass  # 清单上报失败不阻塞执行；终态时会再报一次

    def finalize(self) -> None:
        self._maybe_flush(force=True)
        self._fh.close()
        self._closed = True
        self._report(finalized=True)

    @property
    def local_path(self) -> str:
        return self._local_path
