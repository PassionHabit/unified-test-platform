"""OpenAPI 契约：路径齐全性（V2.1 §11 + §8）。"""
from __future__ import annotations

REQUIRED_PATHS = {
    "/healthz",
    "/api/v1/executions",
    "/api/v1/executions/{execution_id}",
    "/api/v1/executions/{execution_id}/cancel",
    "/api/v1/executions/{execution_id}/events",
    "/api/v1/executions/{execution_id}/logs",
    "/api/v1/executions/{execution_id}/artifacts",
    "/api/v1/projects",
    "/api/v1/projects/{name}",
    "/api/v1/projects/{name}/profiles",
    "/api/v1/nodes",
    "/api/v1/admin/executions/{execution_id}/mark-lost",
    "/agent/v1/poll",
    "/agent/v1/attempts/{attempt_id}/status",
    "/agent/v1/attempts/{attempt_id}/log-manifest",
}


def test_openapi_paths_present(client):
    spec = client.get("/openapi.json").json()
    missing = REQUIRED_PATHS - set(spec["paths"])
    assert not missing, f"missing paths: {missing}"
    assert spec["info"]["title"].startswith("Unified Test Platform")


def test_submit_schema_has_priority_and_timeout(client):
    spec = client.get("/openapi.json").json()
    schema = spec["components"]["schemas"]["ExecutionCreate"]
    assert "priority" in schema["properties"]
    assert "timeout_seconds" in schema["properties"]
