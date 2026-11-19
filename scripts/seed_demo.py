#!/usr/bin/env python3
"""演示数据种子：项目 + Profile（junit 报告）+ 提交一次执行。用法：
  python scripts/seed_demo.py [PYTHON_BIN_FOR_DEMO_TEST]
"""
import base64
import json
import os
import sys
import urllib.request

BASE = os.environ.get("UTP_BASE", "http://127.0.0.1:8000")
PY = sys.argv[1] if len(sys.argv) > 1 else sys.executable

JUNIT = (
    '<?xml version="1.0"?><testsuite name="smoke" tests="3" failures="1">'
    '<testcase name="login_ok" classname="web.Login" time="0.8"/>'
    '<testcase name="search_ok" classname="web.Search" time="1.2"/>'
    '<testcase name="cart_fail" classname="web.Cart" time="0.5">'
    '<failure message="assert">AssertionError: cart empty</failure></testcase></testsuite>'
)

DEMO_CODE = (
    "import os, sys, time, base64\n"
    "print('[robot] starting web smoke suite')\n"
    "time.sleep(2)\n"
    "print('[robot] LOGIN ok')\n"
    "print('[robot] SEARCH ok')\n"
    "print('[robot] CART FAILED: cart empty', file=sys.stderr)\n"
    "time.sleep(1)\n"
    "junit = base64.b64decode('%s').decode()\n"
    "open(os.path.join(os.environ['UTP_ARTIFACTS_DIR'], 'junit.xml'), 'w').write(junit)\n"
    "print('[robot] done')\n" % base64.b64encode(JUNIT.encode()).decode()
)


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")[:300]}


def main():
    print(call("POST", "/api/v1/projects", {
        "name": "robot-web-smoke", "source_type": "git", "repository_ref": "web-tests",
    }))
    argv = [PY, "-c", DEMO_CODE]
    print(call("POST", "/api/v1/projects/robot-web-smoke/profiles", {
        "name": "default", "runtime_image_ref": "robot-chrome:stable",
        "argv": argv, "artifacts": {"report_type": "pytest"}, "timeout_default": 600,
    }))
    status, body = call("POST", "/api/v1/executions", {
        "project_id": "robot-web-smoke", "source_revision": "main",
        "parameters": {"environment": {"base_url": "https://test.example"}},
        "caller": {"type": "human"},
    })
    print("exec:", status, body.get("id"), body.get("status"))
    if status == 202:
        with open("/tmp/utp_demo_exec_id", "w") as fh:
            fh.write(str(body["id"]))


if __name__ == "__main__":
    main()
