"""Agent 侧协议解析测试。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from utp_shared.agent_protocol import AttemptSpec, ControlCommand, PollResponse


def test_poll_response_ignores_unknown_fields():
    body = {
        "assignments": [],
        "commands": [],
        "poll_after_s": 5,
        "some_future_field": {"x": 1},  # 前向兼容
    }
    parsed = PollResponse.model_validate(body)
    assert parsed.poll_after_s == 5


def test_attempt_spec_roundtrip():
    spec = AttemptSpec(
        attempt_id="att-1",
        execution_id="exec-1",
        image="test-browser:stable",
        argv=["robot", "tests/"],
        env={"BASE_URL": "https://x"},
        resources={"cpu": 2, "memory_mb": 4096, "shm_mb": 1024},
    )
    dumped = spec.model_dump(mode="json")
    assert AttemptSpec.model_validate(dumped).attempt_id == "att-1"


def test_attempt_spec_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        AttemptSpec.model_validate(
            {
                "attempt_id": "att-1",
                "execution_id": "exec-1",
                "image": "python:3.12",
                "argv": ["true"],
                "sneaky_injection": "x",
            }
        )


def test_control_command_accepts_cancel():
    parsed = ControlCommand.model_validate({"cancel": {"attempt_id": "att-1", "grace_s": 60}})
    assert parsed.cancel is not None
    assert parsed.cancel.grace_s == 60
