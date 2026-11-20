#!/usr/bin/env python3
"""并发压测脚本（M4）：向运行中的控制面批量提交并跟踪到终态。

用法：
  python scripts/loadtest.py --base http://localhost:8000 --project demo \\
      --count 30 --concurrency 10 [--cancel-after 5]

报告：提交吞吐、终态分布、p50/p95/p99 端到端时延。
注意：真实 200 并发规划需在目标集群执行（V2.1 §15 M4 验收）。
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor


def call(base: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def one_run(base: str, project: str, profile: str) -> dict:
    key = f"load-{uuid.uuid4().hex[:12]}"
    t0 = time.time()
    created = call(base, "POST", "/api/v1/executions", {
        "project_id": project, "profile": profile, "source_revision": "main",
        "caller": {"type": "pipeline", "run_ref": key},
    })
    eid = created["id"]
    while True:
        time.sleep(1)
        body = call(base, "GET", f"/api/v1/executions/{eid}")
        if body["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            body["_elapsed"] = time.time() - t0
            return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--project", required=True)
    ap.add_argument("--profile", default="default")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--concurrency", type=int, default=5)
    args = ap.parse_args()

    print(f"提交 {args.count} 个执行（并发 {args.concurrency}）...")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(
            lambda _: one_run(args.base, args.project, args.profile), range(args.count)))
    total = time.time() - t0

    elapsed = sorted(r["_elapsed"] for r in results)
    dist = {}
    for r in results:
        dist[r["status"]] = dist.get(r["status"], 0) + 1

    def pct(p):
        return elapsed[min(len(elapsed) - 1, int(len(elapsed) * p))]

    print(json.dumps({
        "count": args.count,
        "concurrency": args.concurrency,
        "wall_s": round(total, 1),
        "throughput_per_s": round(args.count / total, 2),
        "status_dist": dist,
        "latency_s": {"p50": round(pct(0.50), 1), "p95": round(pct(0.95), 1),
                      "p99": round(pct(0.99), 1), "max": round(elapsed[-1], 1)},
        "mean_latency_s": round(statistics.mean(elapsed), 1),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
