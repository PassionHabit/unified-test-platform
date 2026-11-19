"""状态机单元测试（utp_shared）。"""
from __future__ import annotations

import pytest

from utp_shared.states import (
    AttemptStatus,
    ExecutionStatus,
    InvalidTransition,
    assert_attempt_transition,
    assert_execution_transition,
    is_attempt_terminal,
    is_execution_terminal,
)


class TestExecutionStateMachine:
    def test_happy_path_to_completed(self):
        for cur, nxt in [
            (ExecutionStatus.QUEUED, ExecutionStatus.PREPARING),
            (ExecutionStatus.PREPARING, ExecutionStatus.STARTING),
            (ExecutionStatus.STARTING, ExecutionStatus.RUNNING),
            (ExecutionStatus.RUNNING, ExecutionStatus.FINALIZING),
            (ExecutionStatus.FINALIZING, ExecutionStatus.COMPLETED),
        ]:
            assert_execution_transition(cur.value, nxt.value)

    def test_queued_direct_cancel(self):
        assert_execution_transition("QUEUED", "CANCELLED")

    def test_cancel_via_cancelling(self):
        assert_execution_transition("RUNNING", "CANCELLING")
        assert_execution_transition("CANCELLING", "CANCELLED")

    def test_reconciling_paths(self):
        assert_execution_transition("RUNNING", "RECONCILING")
        assert_execution_transition("RECONCILING", "RUNNING")
        assert_execution_transition("RECONCILING", "FAILED")

    def test_illegal_jump(self):
        with pytest.raises(InvalidTransition):
            assert_execution_transition("QUEUED", "RUNNING")

    def test_illegal_skip_phase(self):
        with pytest.raises(InvalidTransition):
            assert_execution_transition("PREPARING", "RUNNING")

    @pytest.mark.parametrize("status", ["COMPLETED", "FAILED", "CANCELLED"])
    def test_terminal_is_absorbing(self, status):
        assert is_execution_terminal(status)
        for target in ("QUEUED", "RUNNING", "FAILED"):
            with pytest.raises(InvalidTransition):
                assert_execution_transition(status, target)

    def test_non_terminal_flags(self):
        assert not is_execution_terminal("RUNNING")
        assert not is_execution_terminal("RECONCILING")


class TestAttemptStateMachine:
    def test_happy_path(self):
        assert_attempt_transition("CREATED", "STARTING")
        assert_attempt_transition("STARTING", "RUNNING")
        assert_attempt_transition("RUNNING", "EXITED")

    def test_lost_and_cancel(self):
        assert_attempt_transition("RUNNING", "LOST")
        assert_attempt_transition("CREATED", "CANCELLED")
        assert is_attempt_terminal("LOST")
        assert is_attempt_terminal(AttemptStatus.EXITED.value)

    def test_illegal(self):
        with pytest.raises(InvalidTransition):
            assert_attempt_transition("CREATED", "EXITED")
        with pytest.raises(InvalidTransition):
            assert_attempt_transition("EXITED", "RUNNING")
