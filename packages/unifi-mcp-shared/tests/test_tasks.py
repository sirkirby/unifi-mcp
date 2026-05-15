"""Tests for MCP Tasks adapters."""

from __future__ import annotations

from datetime import datetime, timezone

from mcp.types import CreateTaskResult, Task
from unifi_mcp_shared.tasks import (
    DEFAULT_TASK_POLL_INTERVAL_MS,
    DEFAULT_TASK_TTL_MS,
    MCP_MODEL_IMMEDIATE_RESPONSE_META,
    MCP_RELATED_TASK_META,
    create_task_result_from_job,
    related_task_meta,
    task_from_job_status,
    task_to_dict,
)


def test_task_from_running_job_status():
    task = task_from_job_status(
        "job-123",
        {
            "status": "running",
            "started": 1_700_000_000,
            "result": None,
            "error": None,
        },
    )

    assert isinstance(task, Task)
    assert task.taskId == "job-123"
    assert task.status == "working"
    assert task.statusMessage == "Operation is in progress."
    assert task.createdAt == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
    assert task.lastUpdatedAt == task.createdAt
    assert task.ttl == DEFAULT_TASK_TTL_MS
    assert task.pollInterval == DEFAULT_TASK_POLL_INTERVAL_MS


def test_task_from_completed_job_status_uses_completion_timestamp():
    task = task_from_job_status(
        "job-123",
        {
            "status": "done",
            "started": 1_700_000_000,
            "completed": 1_700_000_030,
            "result": {"success": True},
            "error": None,
        },
        ttl_ms=None,
        poll_interval_ms=None,
    )

    assert task.status == "completed"
    assert task.statusMessage == "Operation completed."
    assert task.createdAt == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
    assert task.lastUpdatedAt == datetime.fromtimestamp(1_700_000_030, tz=timezone.utc)
    assert task.ttl is None
    assert task.pollInterval is None


def test_task_from_failed_job_status_uses_error_message():
    task = task_from_job_status(
        "job-123",
        {
            "status": "error",
            "started": 1_700_000_000,
            "completed": 1_700_000_005,
            "result": None,
            "error": "Controller rejected request",
        },
    )

    assert task.status == "failed"
    assert task.statusMessage == "Controller rejected request"


def test_unknown_job_status_maps_to_failed_task():
    task = task_from_job_status("missing", {"status": "unknown"})

    assert task.status == "failed"
    assert task.statusMessage == "Operation failed."


def test_task_to_dict_uses_protocol_field_names():
    task = task_from_job_status(
        "job-123",
        {
            "status": "running",
            "started": 1_700_000_000,
        },
    )

    payload = task_to_dict(task)

    assert payload == {
        "taskId": "job-123",
        "status": "working",
        "statusMessage": "Operation is in progress.",
        "createdAt": "2023-11-14T22:13:20Z",
        "lastUpdatedAt": "2023-11-14T22:13:20Z",
        "ttl": DEFAULT_TASK_TTL_MS,
        "pollInterval": DEFAULT_TASK_POLL_INTERVAL_MS,
    }


def test_create_task_result_from_job_validates_against_sdk_model():
    payload = create_task_result_from_job(
        "job-123",
        {
            "status": "running",
            "started": 1_700_000_000,
        },
        immediate_message="Started operation. Poll tasks/get for status.",
    )

    parsed = CreateTaskResult.model_validate(payload)
    assert parsed.task.taskId == "job-123"
    assert parsed.task.status == "working"
    assert payload["_meta"] == {MCP_MODEL_IMMEDIATE_RESPONSE_META: "Started operation. Poll tasks/get for status."}


def test_related_task_meta():
    assert related_task_meta("job-123") == {MCP_RELATED_TASK_META: {"taskId": "job-123"}}
