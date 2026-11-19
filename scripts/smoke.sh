#!/usr/bin/env bash
# M0 冒烟：对运行中的控制面走一遍核心契约。
# 用法：BASE_URL=http://localhost:8000 bash scripts/smoke.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
KEY="smoke-$(date +%s)"

echo "== healthz =="
curl -sf "$BASE_URL/healthz" && echo

echo "== 注册项目 =="
curl -sf -X POST "$BASE_URL/api/v1/projects" \
  -H 'Content-Type: application/json' \
  -d '{"name":"smoke-demo","source_type":"git","repository_ref":"demo"}' \
  -o /dev/null -w "%{http_code}\n" || echo "(可能已存在，忽略)"

echo "== 创建 default Profile =="
curl -sf -X POST "$BASE_URL/api/v1/projects/smoke-demo/profiles" \
  -H 'Content-Type: application/json' \
  -d '{"name":"default","runtime_image_ref":"python:3.12-slim","argv":["python","-c","print(1)"]}' \
  -o /dev/null -w "%{http_code}\n" || echo "(可能已存在，忽略)"

echo "== 提交执行（幂等键 ${KEY}）=="
EXEC_ID=$(curl -sf -X POST "$BASE_URL/api/v1/executions" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY" \
  -d '{"project_id":"smoke-demo","source_revision":"main","caller":{"type":"human"}}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "execution_id=$EXEC_ID"

echo "== 幂等重放（应返回同一 id）=="
REPLAY=$(curl -sf -D - -X POST "$BASE_URL/api/v1/executions" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY" \
  -d '{"project_id":"smoke-demo","source_revision":"main","caller":{"type":"human"}}')
echo "$REPLAY" | grep -i 'idempotency-replayed' || echo "缺少重放头！"
REPLAY_ID=$(echo "$REPLAY" | tail -1 | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
[ "$EXEC_ID" = "$REPLAY_ID" ] && echo "重放一致 ✓" || { echo "重放不一致 ✗"; exit 1; }

echo "== 查询状态 =="
curl -sf "$BASE_URL/api/v1/executions/$EXEC_ID" | python3 -m json.tool | head -8

echo "== 取消（QUEUED 立即生效）=="
curl -sf -X POST "$BASE_URL/api/v1/executions/$EXEC_ID/cancel" && echo

echo "== Agent 注册 =="
curl -sf -X POST "$BASE_URL/agent/v1/poll" \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"smoke-agent","cpu_total":8,"memory_mb_total":16384,"labels":["smoke"]}' && echo

echo "== 节点列表 =="
curl -sf "$BASE_URL/api/v1/nodes" | python3 -m json.tool | head -12

echo "SMOKE OK"
