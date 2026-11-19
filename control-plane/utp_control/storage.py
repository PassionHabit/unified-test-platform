"""对象存储（MinIO/S3 兼容）：桶管理、预签名、读写。

控制面持有长期凭据；Agent 只拿短时效预签名 URL，无长期凭据（V2.1 §13）。
测试环境可用本地 MinIO 二进制真实联调。
"""
from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse

from .config import get_settings


class StorageError(RuntimeError):
    pass


def _endpoint_parts(url: str) -> tuple:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    secure = parsed.scheme == "https"
    return parsed.netloc, secure


class ObjectStorage:
    def __init__(self, endpoint: Optional[str] = None, bucket: Optional[str] = None):
        s = get_settings()
        self.endpoint = endpoint or s.s3_endpoint
        self.bucket = bucket or s.s3_bucket
        if not self.endpoint:
            raise StorageError("s3 endpoint not configured")
        host, secure = _endpoint_parts(self.endpoint)
        from minio import Minio

        self._client = Minio(
            host,
            access_key=s.s3_access_key,
            secret_key=s.s3_secret_key,
            secure=secure,
            region=s.s3_region,
        )
        self._bucket_ready = False

    def ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        from minio.error import S3Error

        try:
            self._client.make_bucket(self.bucket)
        except S3Error as exc:
            # 已存在视为成功（bucket_exists 的 HeadBucket 在部分 S3 实现上不兼容）
            if exc.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise
        self._bucket_ready = True

    def presign_put(self, key: str, expires_s: int = 3600) -> str:
        self.ensure_bucket()
        return self._client.presigned_put_object(self.bucket, key, timedelta(seconds=expires_s))

    def presign_get(self, key: str, expires_s: int = 3600) -> str:
        self.ensure_bucket()
        return self._client.presigned_get_object(self.bucket, key, timedelta(seconds=expires_s))

    def get_bytes(self, key: str) -> bytes:
        try:
            resp = self._client.get_object(self.bucket, key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()
        except Exception as exc:
            raise StorageError(f"get {key} failed: {exc}") from exc

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        import io

        self._client.put_object(
            self.bucket, key, io.BytesIO(data), len(data), content_type=content_type
        )

    def stat(self, key: str):
        return self._client.stat_object(self.bucket, key)


@lru_cache
def get_storage() -> ObjectStorage:
    return ObjectStorage()
