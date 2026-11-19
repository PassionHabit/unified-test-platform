PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: setup test agent-test dev-db dev smoke compose-up compose-down compose-logs clean

setup:
	python3 -m venv .venv
	$(PIP) install -U pip
	$(PIP) install -e shared -e control-plane -e agent
	$(PIP) install -e "control-plane[dev]"

test:
	cd control-plane && ../.venv/bin/pytest -q

agent-test:
	cd agent && ../.venv/bin/pytest -q

# 本地 SQLite 开发库（无 Docker 环境）；有 Docker 时用 compose-up 走 PostgreSQL
dev-db:
	cd control-plane && DATABASE_URL=sqlite:///./dev.db ../.venv/bin/alembic upgrade head

dev:
	cd control-plane && DATABASE_URL=sqlite:///./dev.db ../.venv/bin/uvicorn utp_control.main:app --reload --port 8000

smoke:
	bash scripts/smoke.sh

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down -v

compose-logs:
	docker compose logs -f control-plane agent

clean:
	rm -rf .venv control-plane/dev.db
