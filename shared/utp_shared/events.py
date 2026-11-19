"""执行事件类型（execution_event 表 event_type 取值）。"""
from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    EXECUTION_CREATED = "execution.created"
    STATUS_CHANGED = "execution.status_changed"
    CANCEL_REQUESTED = "execution.cancel_requested"
    ATTEMPT_ASSIGNED = "attempt.assigned"
    ATTEMPT_REPORTED = "attempt.reported"
    LOG_MANIFEST_UPDATED = "attempt.log_manifest_updated"
    ARTIFACT_COLLECTED = "execution.artifact_collected"
    RESULT_SUMMARY_PARSED = "execution.result_summary_parsed"
    EXECUTION_FINALIZED = "execution.finalized"
    CALLBACK_REQUESTED = "callback.requested"
