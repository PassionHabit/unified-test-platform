"""执行状态机（V2.1 §7）。

控制面与 Agent 共用；任何状态变更必须经过本模块校验，禁止散落的裸字符串判断。
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable


class ExecutionStatus(str, Enum):
    """业务执行生命周期。终态：COMPLETED / FAILED / CANCELLED。"""

    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    RECONCILING = "RECONCILING"
    CANCELLING = "CANCELLING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AttemptStatus(str, Enum):
    """物理执行实例生命周期。终态：EXITED / LOST / CANCELLED。"""

    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    EXITED = "EXITED"
    LOST = "LOST"
    CANCELLED = "CANCELLED"


class Outcome(str, Enum):
    """测试结论，与平台生命周期正交（不把用例失败当基础设施故障）。"""

    UNKNOWN = "UNKNOWN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_EVALUATED = "NOT_EVALUATED"


class FailureReason(str, Enum):
    NONE = "NONE"
    CANCELLED_BY_USER = "CANCELLED_BY_USER"
    SOURCE_FETCH_FAILED = "SOURCE_FETCH_FAILED"
    PREPARE_FAILED = "PREPARE_FAILED"
    IMAGE_PULL_FAILED = "IMAGE_PULL_FAILED"
    CONTAINER_OOM_KILLED = "CONTAINER_OOM_KILLED"
    NODE_LOST = "NODE_LOST"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    PROCESS_EXIT_NONZERO = "PROCESS_EXIT_NONZERO"
    ARTIFACT_UPLOAD_FAILED = "ARTIFACT_UPLOAD_FAILED"
    SERVICE_BEFORE_FAILED = "SERVICE_BEFORE_FAILED"  # M3
    SECRET_RESOLVE_FAILED = "SECRET_RESOLVE_FAILED"  # M3


def _fs(values: Iterable[ExecutionStatus]) -> frozenset:
    return frozenset(v.value for v in values)


# 合法状态迁移表。QUEUED 可直达 CANCELLED：尚未启动任何执行物，无需经过 CANCELLING。
EXECUTION_TRANSITIONS: dict = {
    ExecutionStatus.QUEUED.value: _fs(
        {ExecutionStatus.PREPARING, ExecutionStatus.CANCELLING, ExecutionStatus.CANCELLED, ExecutionStatus.FAILED}
    ),
    ExecutionStatus.PREPARING.value: _fs(
        {ExecutionStatus.STARTING, ExecutionStatus.CANCELLING, ExecutionStatus.FAILED}
    ),
    ExecutionStatus.STARTING.value: _fs(
        {ExecutionStatus.RUNNING, ExecutionStatus.RECONCILING, ExecutionStatus.CANCELLING, ExecutionStatus.FAILED}
    ),
    ExecutionStatus.RUNNING.value: _fs(
        {ExecutionStatus.FINALIZING, ExecutionStatus.RECONCILING, ExecutionStatus.CANCELLING}
    ),
    ExecutionStatus.RECONCILING.value: _fs(
        {ExecutionStatus.RUNNING, ExecutionStatus.FINALIZING, ExecutionStatus.CANCELLING, ExecutionStatus.FAILED}
    ),
    ExecutionStatus.CANCELLING.value: _fs({ExecutionStatus.CANCELLED, ExecutionStatus.FAILED}),
    ExecutionStatus.FINALIZING.value: _fs({ExecutionStatus.COMPLETED, ExecutionStatus.FAILED}),
    ExecutionStatus.COMPLETED.value: frozenset(),
    ExecutionStatus.FAILED.value: frozenset(),
    ExecutionStatus.CANCELLED.value: frozenset(),
}

ATTEMPT_TRANSITIONS: dict = {
    AttemptStatus.CREATED.value: frozenset(
        {AttemptStatus.STARTING.value, AttemptStatus.CANCELLED.value}
    ),
    AttemptStatus.STARTING.value: frozenset(
        {AttemptStatus.RUNNING.value, AttemptStatus.LOST.value, AttemptStatus.CANCELLED.value}
    ),
    AttemptStatus.RUNNING.value: frozenset(
        {AttemptStatus.EXITED.value, AttemptStatus.LOST.value, AttemptStatus.CANCELLED.value}
    ),
    AttemptStatus.EXITED.value: frozenset(),
    AttemptStatus.LOST.value: frozenset(),
    AttemptStatus.CANCELLED.value: frozenset(),
}

EXECUTION_TERMINAL = frozenset(
    {ExecutionStatus.COMPLETED.value, ExecutionStatus.FAILED.value, ExecutionStatus.CANCELLED.value}
)
ATTEMPT_TERMINAL = frozenset(
    {AttemptStatus.EXITED.value, AttemptStatus.LOST.value, AttemptStatus.CANCELLED.value}
)


class InvalidTransition(ValueError):
    """非法状态迁移。"""

    def __init__(self, kind: str, current: str, target: str):
        super().__init__(f"illegal {kind} transition: {current} -> {target}")
        self.kind = kind
        self.current = current
        self.target = target


def assert_execution_transition(current: str, target: str) -> None:
    _assert_transition("execution", EXECUTION_TRANSITIONS, current, target)


def assert_attempt_transition(current: str, target: str) -> None:
    _assert_transition("attempt", ATTEMPT_TRANSITIONS, current, target)


def _assert_transition(kind: str, table: dict, current: str, target: str) -> None:
    allowed = table.get(current)
    if allowed is None:
        raise InvalidTransition(kind, current, target)
    if target not in allowed:
        raise InvalidTransition(kind, current, target)


def is_execution_terminal(status: str) -> bool:
    return status in EXECUTION_TERMINAL


def is_attempt_terminal(status: str) -> bool:
    return status in ATTEMPT_TERMINAL
