"""秘密引用（M3）：值 Fernet 加密存库，键来自 UTP_SECRET_KEY。

仅经 env 注入容器；不进 argv/日志/context_json/产物（V2.1 §6/§13）。
参数值形如 {"$secret": "name"} 时在领取任务时解析替换。
"""
from __future__ import annotations

import base64
import hashlib

from .config import get_settings


class SecretError(RuntimeError):
    pass


def _fernet():
    from cryptography.fernet import Fernet

    key_material = get_settings().secret_key or "utp-dev-only-secret-key"
    digest = hashlib.sha256(key_material.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception as exc:
        raise SecretError("decrypt failed (wrong UTP_SECRET_KEY?)") from exc


def is_secret_ref(value) -> bool:
    return isinstance(value, dict) and set(value.keys()) == {"$secret"} and isinstance(value["$secret"], str)


def resolve_secret_refs(env: dict, lookup) -> dict:
    """解析 env 中的 {"$secret": name}；lookup(name) -> 明文。返回新 dict。"""
    resolved = {}
    for k, v in env.items():
        if is_secret_ref(v):
            resolved[k] = lookup(v["$secret"])
        else:
            resolved[k] = v
    return resolved
