"""MCP Tasks adapters for UniFi compatibility job state.

The existing UniFi batch meta-tools expose ``jobId`` values backed by
``unifi_core.jobs.JobStore``. This module keeps that compatibility surface
unchanged while providing a small, typed bridge to the experimental MCP Tasks
shape introduced in protocol revision 2025-11-25.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from mcp.types import CreateTaskResult, Task

MCP_RELATED_TASK_META = "io.modelcontextprotocol/related-task"
MCP_MODEL_IMMEDIATE_RESPONSE_META = "io.modelcontextprotocol/model-immediate-response"

DEFAULT_TASK_TTL_MS = 600_000
DEFAULT_TASK_POLL_INTERVAL_MS = 1_000

TaskStatus = Literal["working", "input_required", "completed", "failed", "cancelled"]

_JOB_STATUS_TO_TASK_STATUS: dict[str, TaskStatus] = {
    "running": "working",
    "done": "completed",
    "error": "failed",
    "unknown": "failed",
}

_TASK_STATUS_TO_MESSAGE: dict[TaskStatus, str] = {
    "working": "Operation is in progress.",
    "completed": "Operation completed.",
    "cancelled": "Operation was cancelled.",
    "input_required": "Operation requires additional input.",
}


def _timestamp_to_datetime(value: Any, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if fallback is not None:
        return fallback
    return datetime.now(timezone.utc)


def _status_message(job_status: dict[str, Any], task_status: TaskStatus) -> str:
    if task_status == "failed":
        return str(job_status.get("error") or "Operation failed.")
    return _TASK_STATUS_TO_MESSAGE.get(task_status, "Operation requires additional input.")


def task_from_job_status(
    job_id: str,
    job_status: dict[str, Any],
    *,
    ttl_ms: int | None = DEFAULT_TASK_TTL_MS,
    poll_interval_ms: int | None = DEFAULT_TASK_POLL_INTERVAL_MS,
) -> Task:
    """Convert UniFi compatibility job status to an MCP ``Task`` model."""
    task_status = _JOB_STATUS_TO_TASK_STATUS.get(str(job_status.get("status")), "failed")
    created_at = _timestamp_to_datetime(job_status.get("started"))
    last_updated_at = _timestamp_to_datetime(job_status.get("completed"), fallback=created_at)

    return Task(
        taskId=job_id,
        status=task_status,
        statusMessage=_status_message(job_status, task_status),
        createdAt=created_at,
        lastUpdatedAt=last_updated_at,
        ttl=ttl_ms,
        pollInterval=poll_interval_ms,
    )


def task_to_dict(task: Task) -> dict[str, Any]:
    """Serialize an MCP task model using protocol field names."""
    return task.model_dump(mode="json", by_alias=True, exclude_none=True)


def create_task_result_from_job(
    job_id: str,
    job_status: dict[str, Any],
    *,
    ttl_ms: int | None = DEFAULT_TASK_TTL_MS,
    poll_interval_ms: int | None = DEFAULT_TASK_POLL_INTERVAL_MS,
    immediate_message: str | None = None,
) -> dict[str, Any]:
    """Build the ``CreateTaskResult`` shape for a task-backed job."""
    task = task_from_job_status(
        job_id,
        job_status,
        ttl_ms=ttl_ms,
        poll_interval_ms=poll_interval_ms,
    )
    meta = None
    if immediate_message is not None:
        meta = {MCP_MODEL_IMMEDIATE_RESPONSE_META: immediate_message}
    result = CreateTaskResult(task=task, _meta=meta)
    return result.model_dump(mode="json", by_alias=True, exclude_none=True)


def related_task_meta(task_id: str) -> dict[str, Any]:
    """Return MCP related-task metadata for task-associated messages."""
    return {MCP_RELATED_TASK_META: {"taskId": task_id}}
