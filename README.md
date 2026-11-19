# unified-test-platform

统一自动化测试执行平台：为人工与流水线提供一站式的自动化测试执行服务——源码版本固化、参数解析、资源调度、容器/原生执行、公共服务调用、状态追踪、日志与原始产物交付。

## 设计文档

- [V2.0 设计基线（当前）](docs/automation_execution_platform_design_v2.md)
- [V1.0 草案（存档）](docs/automation_execution_platform_design_v1.md)

## 技术栈

PostgreSQL · MinIO · FastAPI (Python) · Docker Agent · React + TypeScript + Ant Design

## 快速开始

```bash
make setup      # 建 .venv 并安装 shared / control-plane / agent
make test       # 控制面测试（SQLite + Alembic 真实迁移）
make agent-test # Agent 协议测试
make dev-db     # 本地 SQLite 开发库
make dev        # 启动控制面（http://localhost:8000/docs）
make smoke      # 端到端冒烟（另开终端，服务启动后执行）
make compose-up # PG + MinIO + 控制面 + Agent（需 Docker）
```

无 Docker 环境时走 SQLite 路线（make dev-db / make dev / make smoke）；compose 文件已备好，待有 Docker 的机器验证。

## 状态

**M0 已完成**（骨架 + 数据模型 + API 契约 + 状态机 + 48 项测试 + SQLite 冒烟）。下一步 M1：端到端执行闭环 + 最小控制台。项目管理看板：[GitHub Project #1](https://github.com/users/PassionHabit/projects/1)
