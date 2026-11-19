"""源码快照服务（M3，V2.1 §4.2）。

- 解析：branch/tag → 精确 commit（git ls-remote / svn info），提交时固化
- 获取：git archive（远程直取，不整仓 clone）/ svn export
- 缓存：按 (repo, 精确版本) 内容寻址；命中直接复用对象
- 上传：tar.gz → 对象存储 snapshots/{repo_hash}/{version}/{sha}.tar.gz

SVN 依赖本机 svn CLI；缺失时对应适配器显式报错（不假装成功）。
"""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
from typing import Optional


class SourceError(RuntimeError):
    pass


def _run(cmd: list, cwd: Optional[str] = None, timeout: int = 600) -> str:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError as exc:
        raise SourceError(f"required binary not installed: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SourceError(f"command timed out: {' '.join(cmd[:3])}") from exc
    if proc.returncode != 0:
        raise SourceError(
            f"command failed ({proc.returncode}): {' '.join(cmd[:4])} :: "
            f"{proc.stderr.strip()[:300]}"
        )
    return proc.stdout


def resolve_git_revision(repo_url: str, revision: str) -> str:
    """branch/tag/commit → 40 位 commit（git ls-remote，无需本地克隆）。"""
    out = _run(["git", "ls-remote", repo_url], timeout=120)
    for line in out.splitlines():
        if not line.strip():
            continue
        commit, _, ref = line.partition("\t")
        ref = ref.strip()
        if (
            ref == f"refs/heads/{revision}"
            or ref == f"refs/tags/{revision}"
            or ref == f"refs/tags/{revision}^{{}}"
            or commit == revision
        ):
            if len(commit) >= 40:
                return commit
    raise SourceError(f"revision '{revision}' not found in {repo_url}")


def resolve_svn_revision(repo_url: str, revision: str) -> str:
    """SVN：revision 为数字直接用；否则取 HEAD（svn info）。"""
    if revision.isdigit():
        return revision
    out = _run(["svn", "info", repo_url], timeout=120)
    for line in out.splitlines():
        if line.startswith("Revision:"):
            return line.split(":", 1)[1].strip()
    raise SourceError(f"cannot resolve svn revision for {repo_url}")


def snapshot_key(source_type: str, repo_url: str, exact_revision: str) -> str:
    repo_hash = hashlib.sha256(f"{source_type}:{repo_url}".encode()).hexdigest()[:16]
    rev_hash = hashlib.sha256(exact_revision.encode()).hexdigest()[:16]
    return f"snapshots/{source_type}/{repo_hash}/{rev_hash}.tar.gz"


def fetch_git_archive(repo_url: str, commit: str, dest_tar: str) -> None:
    """git archive --remote 直接取指定 commit 的 tar（服务端需支持，GitLab/Gitea 均可；
    不支持时本地浅克隆回退）。"""
    try:
        with open(dest_tar, "wb") as fh:
            proc = subprocess.run(
                ["git", "archive", "--format=tar.gz", "--remote", repo_url, commit],
                stdout=fh,
                stderr=subprocess.PIPE,
                timeout=1200,
            )
        if proc.returncode == 0:
            return
    except FileNotFoundError as exc:
        raise SourceError("git not installed") from exc
    # 回退：浅克隆 + 本地 archive（svn 式场景/哑协议）
    with tempfile.TemporaryDirectory(prefix="utp-git-") as tmp:
        _run(["git", "clone", "--no-checkout", "--depth=1", repo_url, tmp], timeout=1800)
        _run(["git", "fetch", "--depth=1", "origin", commit], cwd=tmp, timeout=1800)
        _run(["git", "archive", "--format=tar.gz", commit, "-o", dest_tar], cwd=tmp)


def fetch_svn_export(repo_url: str, revision: str, dest_tar: str) -> None:
    """svn export → 打 tar.gz。"""
    import os
    import tarfile

    with tempfile.TemporaryDirectory(prefix="utp-svn-") as tmp:
        target = os.path.join(tmp, "src")
        _run(["svn", "export", "-r", revision, repo_url, target], timeout=1800)
        with tarfile.open(dest_tar, "w:gz") as tar:
            tar.add(target, arcname=".")


def ensure_snapshot(source_type: str, repo_url: str, exact_revision: str, storage) -> str:
    """内容寻址快照：命中缓存直接复用；否则拉取+上传。返回对象 key。"""
    key = snapshot_key(source_type, repo_url, exact_revision)
    try:
        storage.stat(key)
        return key  # 缓存命中
    except Exception:
        pass  # 未命中，走拉取

    import os

    with tempfile.TemporaryDirectory(prefix="utp-snap-") as tmp:
        tar_path = os.path.join(tmp, "snapshot.tar.gz")
        if source_type == "git":
            fetch_git_archive(repo_url, exact_revision, tar_path)
        elif source_type == "svn":
            fetch_svn_export(repo_url, exact_revision, tar_path)
        else:
            raise SourceError(f"unsupported source type: {source_type}")
        with open(tar_path, "rb") as fh:
            storage._client.put_object(
                storage.bucket, key, fh, os.path.getsize(tar_path),
                content_type="application/gzip",
            )
    return key


def resolve_revision(source_type: str, repo_url: str, revision: str) -> str:
    if source_type == "git":
        return resolve_git_revision(repo_url, revision)
    if source_type == "svn":
        return resolve_svn_revision(repo_url, revision)
    raise SourceError(f"unsupported source type: {source_type}")
