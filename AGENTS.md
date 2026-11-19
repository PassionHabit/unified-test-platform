# AGENTS.md — 给 AI 助手的工作约定

本仓库的实现基线是 `docs/automation_execution_platform_design_v2.md`（V2.1）。动手前先读它。

## 铁律

1. **按里程碑推进**：M0（骨架+契约）→ M1（E2E 闭环+最小控制台）→ M2（调度+可靠性）→ M3（接入+服务）→ M4（运维+压测）。不跳步、不超前实现被排除的能力（K8s/Nomad、Selenium Grid、DAG 编排、资源互斥、结果深度分析）。
2. **状态变更必须走 `shared/utp_shared/states.py`** 的状态机校验，禁止裸字符串比较。`status`/`outcome`/`failure_reason` 三者语义不得混用。
3. **幂等**：执行提交靠 `(caller_scope, request_id)` 唯一约束 + Idempotency-Key 重放；Agent start 靠 attempt_id 幂等。
4. **命令必须是数组**（argv），绝不拼接 shell 字符串；敏感值只走 env，不进 argv / 日志 / context_json / 产物。
5. **禁止用 Mock 成功冒充端到端**：M1 起必须有真实 Docker 执行验证。
6. **对齐三份契约**：SQLAlchemy 模型（`control-plane/utp_control/models/`）、Alembic 迁移、`tests/test_migration.py` 的表集合一致性检查。改模型必须同步迁移。
7. Agent 侧协议消息统一定义在 `shared/utp_shared/agent_protocol.py`，前后兼容（未知字段 ignore / 禁新增必填字段）；AttemptSpec 是不可变契约。

## 常用命令

```bash
make setup        # 建 .venv 并安装 shared / control-plane / agent
make test         # 控制面测试（SQLite + Alembic 真实迁移）
make agent-test   # Agent 协议测试
make dev-db       # 本地 SQLite 开发库（迁移）
make dev          # 启动控制面（SQLite 模式）
make smoke        # 端到端冒烟（需服务已启动）
make compose-up   # PG + MinIO + 控制面 + Agent（需 Docker）
```

## 提交规范

每个里程碑提交包含：代码、迁移、配置示例、测试、README 更新；提交说明写清变更摘要、验证命令与结果、已知限制。无 Docker 环境时明确标注"compose 未验证"。
