# unified-test-platform

统一自动化测试执行平台：为人工与流水线提供一站式测试执行服务——源码版本固化、参数解析、资源调度、容器/原生执行、公共服务编排、状态追踪、日志与产物交付、轻量结果摘要。

## 设计文档

- [V2.1 设计基线（当前）](docs/automation_execution_platform_design_v2.md)
- [V1.0 草案（存档）](docs/automation_execution_platform_design_v1.md)

## 架构

```
人工控制台(React+AntD) ─┐
                        ├→ 控制面 FastAPI ─→ PostgreSQL ── 执行/Attempt/预留/事件
既有流水线 ─────────────┘      │      └────→ MinIO ────── 快照/日志分片/产物
                               │
        ┌──────────────────────┴──────────────────┐
   Docker Agent（执行机）                  Native Agent（特殊机器）
   容器执行 · 日志分片直传 · 产物直传      本地进程组执行
        └──── 长轮询(mTLS 规划) + 死线看门狗 + 幂等上报 ────┘
```

- **状态机**：Execution（QUEUED→…→COMPLETED/FAILED/CANCELLED）与 Attempt（物理执行）分离；`status`/`outcome`/`failure_reason` 三分，不把用例失败当平台故障
- **调度**：部门公平轮询 + 部门并发配额 + priority + 标签/容量过滤，事务内原子领取预留
- **可靠性**：心跳对账（RECONCILING 双向收敛）、死线看门狗（Agent 本地执法）、mark-lost（确认令牌）、节点排水/恢复、outbox 回调（至少一次 + 白名单）

## 里程碑状态

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 骨架、16+3 表迁移、API 契约、状态机 | ✅ |
| M1 | 端到端闭环：调度分配→真实执行→日志/产物（预签名直传）→junit/robot 解析；Web 控制台（提交/列表/详情/时间线/日志/产物/取消） | ✅ |
| M2 | 部门公平与配额、心跳对账、mark-lost、排水、资源预留释放 | ✅ |
| M3 | Git/SVN 快照（内容寻址缓存）、prepare 步骤、秘密引用（加密存储→env 注入）、服务目录（async_poll before/during/after + 清理） | ✅ |
| M4 | API 令牌 + 部门隔离、outbox 回调、/metrics、镜像库 API、压测脚本 | ✅ |

**测试**：控制面 65 + Agent 4 = 69 项全过（含三个真实 E2E 套件：真 HTTP + 真 S3(moto) + 真子进程执行；真 git 仓库快照；真异步公共服务生命周期）。本地 6 并发压测全 COMPLETED。

## 快速开始

```bash
make setup          # 建 .venv 并安装 shared / control-plane / agent
make test           # 控制面测试（SQLite + 真实迁移 + E2E）
make agent-test     # Agent 协议测试
make dev-db         # 本地 SQLite 开发库
make dev            # 控制面（http://localhost:8000/docs）
bash scripts/smoke.sh                      # API 冒烟
python scripts/seed_demo.py "$(pwd)/.venv/bin/python"   # 演示项目+执行
UTP_CONTROL_URL=http://localhost:8000 .venv/bin/python -m utp_agent   # 启动 Agent

cd web && npm install && npm run dev       # 控制台（http://localhost:5173）
python scripts/loadtest.py --base http://localhost:8000 --project robot-web-smoke --count 6 --concurrency 6
make compose-up     # PG + MinIO + 控制面 + Agent（需 Docker）
```

## 生产部署要点

- `DATABASE_URL=postgresql+psycopg2://...`（PG 上自动启用 SKIP LOCKED 并发领取）
- `S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY/S3_BUCKET` → MinIO
- `AUTH_ENABLED=true` + `POST /api/v1/tokens` 签发（默认关闭仅供本地开发）
- `UTP_SECRET_KEY`（秘密引用加密键）与 `CALLBACK_ALLOWLIST`（回调白名单，防 SSRF）
- Agent：`UTP_CONTROL_URL` 指向控制面，`UTP_NODE_TYPE=docker|native`

## 已知限制（如实）

- Docker 执行器已实现但本机无 Docker，真实容器执行待 Docker 主机验证（compose 已备）
- 真实 200 并发压测需在 10~30 节点目标集群执行（本地仅验证过 6 并发逻辑正确性）
- SSO/LDAP 对接点已预留（`resolve_external_identity`），待公司接入方式确认
- Dockerfile 镜像构建流水线待 Harbor 接入；预制公共服务（日志检查/精准测试初始化）待接口规范就绪后由管理员登记
- Agent 与控制面通信的 mTLS 在 M2 规划中，当前开发模式明文

## 项目管理

[GitHub Project #1](https://github.com/users/PassionHabit/projects/1)
