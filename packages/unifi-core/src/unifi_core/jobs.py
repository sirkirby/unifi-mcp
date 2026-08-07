"""Background job management for long-running MCP server operations.

This module provides an in-memory job store for tracking asynchronous operations
like device upgrades, bulk configuration changes, and other long-running tasks.

Example:
    job_id = await JOBS.start(some_async_operation())
    status = await JOBS.status(job_id)
"""

import asyncio
import logging
import math
import secrets
import time
from typing import Any, Callable, Coroutine, Dict

logger = logging.getLogger(__name__)

DEFAULT_JOB_RETENTION_SECONDS = 60 * 60
DEFAULT_MAX_COMPLETED_JOBS = 1_000


class JobStore:
    """In-memory store for tracking background job states.

    Manages the lifecycle of asynchronous jobs including starting, tracking,
    and retrieving status. Jobs are stored with their state, start time,
    and eventual results or errors.

    Attributes:
        _jobs: Dictionary mapping job IDs to job state dictionaries
        _lock: Asyncio lock for thread-safe access to the job store
    """

    def __init__(
        self,
        *,
        retention_seconds: float = DEFAULT_JOB_RETENTION_SECONDS,
        max_completed_jobs: int = DEFAULT_MAX_COMPLETED_JOBS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Initialize an empty job store with bounded terminal-job retention.

        Completed and failed jobs remain queryable for at most
        ``retention_seconds`` and are additionally capped at
        ``max_completed_jobs``. Running jobs are never evicted. The clock is
        injectable so retention behavior can be tested without sleeping.
        """
        if not math.isfinite(retention_seconds) or retention_seconds < 0:
            raise ValueError("retention_seconds must be finite and non-negative")
        if isinstance(max_completed_jobs, bool) or not isinstance(max_completed_jobs, int) or max_completed_jobs < 0:
            raise ValueError("max_completed_jobs must be a non-negative integer")

        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._retention_seconds = retention_seconds
        self._max_completed_jobs = max_completed_jobs
        self._clock = clock

    def _prune_locked(self, now: float) -> None:
        """Evict expired and excess terminal jobs while ``_lock`` is held."""
        terminal = [(job_id, job) for job_id, job in self._jobs.items() if job["status"] in {"done", "error"}]

        expired_ids = {job_id for job_id, job in terminal if now - job["completed"] >= self._retention_seconds}
        for job_id in expired_ids:
            del self._jobs[job_id]

        retained_terminal = [(job_id, job) for job_id, job in terminal if job_id not in expired_ids]
        excess = len(retained_terminal) - self._max_completed_jobs
        if excess > 0:
            retained_terminal.sort(
                key=lambda item: (
                    item[1]["completed"],
                    item[1]["started"],
                    item[0],
                )
            )
            for job_id, _job in retained_terminal[:excess]:
                del self._jobs[job_id]

        removed = len(expired_ids) + max(excess, 0)
        if removed:
            logger.debug("Pruned %s completed background jobs", removed)

    async def start(self, coro: Coroutine[Any, Any, Any]) -> str:
        """Start a background job and return its unique identifier.

        Creates a new job entry with a unique ID, initializes its state to 'running',
        and launches the coroutine in a background task. The task automatically
        updates the job state to 'done' or 'error' upon completion.

        Args:
            coro: The coroutine to execute as a background job

        Returns:
            A unique job identifier (16-character hex string)
        """
        job_id = secrets.token_hex(8)

        async with self._lock:
            now = self._clock()
            self._prune_locked(now)
            self._jobs[job_id] = {
                "status": "running",
                "started": now,
                "result": None,
                "error": None,
            }

        logger.info("Starting background job %s", job_id)

        async def _runner() -> None:
            """Internal runner that executes the coroutine and updates job state."""
            try:
                result = await coro
                async with self._lock:
                    if job_id in self._jobs:
                        completed = self._clock()
                        self._jobs[job_id]["status"] = "done"
                        self._jobs[job_id]["result"] = result
                        self._jobs[job_id]["completed"] = completed
                        self._prune_locked(completed)
                logger.info("Background job %s completed successfully", job_id)
            except Exception as e:
                async with self._lock:
                    if job_id in self._jobs:
                        completed = self._clock()
                        self._jobs[job_id]["status"] = "error"
                        self._jobs[job_id]["error"] = str(e)
                        self._jobs[job_id]["completed"] = completed
                        self._prune_locked(completed)
                logger.error("Background job %s failed with error: %s", job_id, e, exc_info=True)

        # Launch the runner as a background task
        asyncio.create_task(_runner())

        return job_id

    async def status(self, job_id: str) -> Dict[str, Any]:
        """Retrieve the current status of a job.

        Args:
            job_id: The unique identifier of the job to query

        Returns:
            A dictionary containing the job's state including:
            - status: 'running', 'done', 'error', or 'unknown'
            - started: Unix timestamp when the job started (if known)
            - completed: Unix timestamp when the job finished (if completed)
            - result: The return value of the job (if completed successfully)
            - error: Error message (if failed)
        """
        async with self._lock:
            self._prune_locked(self._clock())
            if job_id not in self._jobs:
                logger.warning("Status requested for unknown job ID: %s", job_id)
                return {"status": "unknown"}

            # Return a copy to prevent external modifications
            return dict(self._jobs[job_id])


# Global singleton instance
JOBS = JobStore()


async def start_async_tool(
    handler: Callable[..., Coroutine[Any, Any, Dict[str, Any]]], args: Dict[str, Any]
) -> Dict[str, Any]:
    """Start a tool handler as a background job.

    Wraps a tool handler function in a background job and returns the job ID
    for later status checking. This allows long-running operations to be
    executed asynchronously without blocking the MCP server.

    Args:
        handler: The async function to execute (typically a tool handler)
        args: Dictionary of arguments to pass to the handler

    Returns:
        A dictionary containing the job ID: {"jobId": "abc123def456"}
    """
    try:
        # Create a coroutine by calling the handler with unpacked args
        coro = handler(**args)
        job_id = await JOBS.start(coro)
        logger.info("Started async tool job %s with handler %s", job_id, handler.__name__)
        return {"jobId": job_id}
    except Exception as e:
        logger.error("Failed to start async tool: %s", e, exc_info=True)
        return {"error": f"Failed to start async tool: {e}"}


async def get_job_status(job_id: str) -> Dict[str, Any]:
    """Retrieve the status of a background job.

    A convenience wrapper around JobStore.status() for easier access
    in tool handlers.

    Args:
        job_id: The unique identifier of the job to query

    Returns:
        A dictionary containing the job's current state
    """
    return await JOBS.status(job_id)
