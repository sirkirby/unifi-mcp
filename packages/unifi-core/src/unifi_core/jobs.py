"""Background job management for long-running MCP server operations.

This module provides an in-memory job store for tracking asynchronous operations
like device upgrades, bulk configuration changes, and other long-running tasks.

A job moves through these states:

- ``queued``: waiting for its turn. Either it was started ``after`` an earlier
  job that has not yet joined the controller's gate (``position`` is ``None``),
  or it is waiting in the gate's write queue (``position`` counts the write
  operations ahead of it, ``1`` meaning next).
- ``running``: executing. A job starts ``running`` unless it was chained, and
  shows ``queued`` only while it actually waits for the write gate.
- ``done``, ``error``, ``cancelled``: finished. ``cancelled`` means the job's
  operation never ran; a job cancelled after its write turn was granted is
  reported as ``error``, since its change may have reached the controller.

Ordering: each job runs inside an observer (``unifi_core.operation_gate``) that
marks it *admitted* once it joins a gate, or when it finishes. A job started
with ``after=<job id>`` waits for that job's admission before its coroutine
starts, so a batch of jobs reaches the gate's queue in submission order no
matter what each one awaits first.

Example:
    job_id = await JOBS.start(some_async_operation())
    status = await JOBS.status(job_id)
"""

import asyncio
import logging
import math
import secrets
import time
from contextvars import ContextVar
from typing import Any, Callable, Coroutine, Dict

from unifi_core.operation_gate import WriteTicket, observing_operations

logger = logging.getLogger(__name__)

DEFAULT_JOB_RETENTION_SECONDS = 60 * 60
DEFAULT_MAX_COMPLETED_JOBS = 1_000

TERMINAL_JOB_STATUSES = frozenset({"done", "error", "cancelled"})

_current_job: ContextVar[str | None] = ContextVar("unifi_current_job", default=None)


def current_job_id() -> str | None:
    """The id of the background job running the current code, or ``None``."""
    return _current_job.get()


class _JobRun:
    """What the store needs while a job is live; dropped once it finishes."""

    __slots__ = ("admitted", "coro", "coro_started", "task", "ticket", "write_granted")

    def __init__(self, coro: Coroutine[Any, Any, Any]) -> None:
        self.coro = coro
        self.coro_started = False
        self.admitted = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.ticket: WriteTicket | None = None
        self.write_granted = False


class _JobObserver:
    """Routes one job's gate events to its store."""

    __slots__ = ("_job_id", "_store")

    def __init__(self, store: "JobStore", job_id: str) -> None:
        self._store = store
        self._job_id = job_id

    def admitted(self) -> None:
        self._store._mark_admitted(self._job_id)

    def queued(self, ticket: WriteTicket) -> None:
        self._store._mark_queued(self._job_id, ticket)

    def granted(self, ticket: WriteTicket) -> None:
        self._store._mark_granted(self._job_id, ticket)


class JobStore:
    """In-memory store for tracking background job states.

    Manages the lifecycle of asynchronous jobs including starting, tracking,
    and retrieving status. Jobs are stored with their state, start time,
    and eventual results or errors. The store keeps a reference to every task
    it starts until the task finishes, so a job is never garbage-collected
    mid-flight.

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

        Completed, failed and cancelled jobs remain queryable for at most
        ``retention_seconds`` and are additionally capped at
        ``max_completed_jobs``. Queued and running jobs are never evicted. The
        clock is injectable so retention behavior can be tested without sleeping.
        """
        if not math.isfinite(retention_seconds) or retention_seconds < 0:
            raise ValueError("retention_seconds must be finite and non-negative")
        if isinstance(max_completed_jobs, bool) or not isinstance(max_completed_jobs, int) or max_completed_jobs < 0:
            raise ValueError("max_completed_jobs must be a non-negative integer")

        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._runs: Dict[str, _JobRun] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._retention_seconds = retention_seconds
        self._max_completed_jobs = max_completed_jobs
        self._clock = clock

    def _prune_locked(self, now: float) -> None:
        """Evict expired and excess terminal jobs while ``_lock`` is held."""
        terminal = [(job_id, job) for job_id, job in self._jobs.items() if job["status"] in TERMINAL_JOB_STATUSES]

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

    # ------------------------------------------------------------------
    # State transitions. Each runs without awaiting, so none interleaves
    # with another on the event loop.
    # ------------------------------------------------------------------

    def _finish(self, job_id: str, status: str, *, result: Any = None, error: str | None = None) -> None:
        job = self._jobs.get(job_id)
        run = self._runs.pop(job_id, None)
        if run is not None:
            run.admitted.set()
        if job is None:
            return
        completed = self._clock()
        job["status"] = status
        job["result"] = result
        job["error"] = error
        job["completed"] = completed
        self._prune_locked(completed)

    def _mark_admitted(self, job_id: str) -> None:
        run = self._runs.get(job_id)
        if run is not None:
            run.admitted.set()

    def _mark_queued(self, job_id: str, ticket: WriteTicket) -> None:
        job, run = self._jobs.get(job_id), self._runs.get(job_id)
        if job is None or run is None or job["status"] != "running" or not ticket.waiting:
            return
        run.ticket = ticket
        job["status"] = "queued"

    def _mark_granted(self, job_id: str, ticket: WriteTicket) -> None:
        job, run = self._jobs.get(job_id), self._runs.get(job_id)
        if job is None or run is None or job["status"] in TERMINAL_JOB_STATUSES:
            return
        run.ticket = None
        run.write_granted = True
        job["status"] = "running"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self, coro: Coroutine[Any, Any, Any], *, after: str | None = None) -> str:
        """Start a background job and return its unique identifier.

        Creates a new job entry with a unique ID and launches the coroutine in
        a background task. The task updates the job state to ``done``,
        ``error`` or ``cancelled`` when it finishes.

        Args:
            coro: The coroutine to execute as a background job
            after: Start the coroutine only once this job is admitted (has
                joined a controller gate, or finished). The new job shows
                ``queued`` until then. An unknown or finished job does not
                hold it back.

        Returns:
            A unique job identifier (16-character hex string)
        """
        job_id = secrets.token_hex(8)
        run = _JobRun(coro)
        predecessor = self._runs.get(after) if after is not None else None

        async with self._lock:
            now = self._clock()
            self._prune_locked(now)
            self._jobs[job_id] = {
                "status": "queued" if predecessor is not None else "running",
                "started": now,
                "result": None,
                "error": None,
            }
            self._runs[job_id] = run

        logger.info("Starting background job %s", job_id)

        observer = _JobObserver(self, job_id)

        async def _runner() -> None:
            """Internal runner that executes the coroutine and updates job state."""
            _current_job.set(job_id)
            try:
                if predecessor is not None:
                    await predecessor.admitted.wait()
                job = self._jobs.get(job_id)
                if job is None or job["status"] in TERMINAL_JOB_STATUSES:
                    coro.close()
                    return
                job["status"] = "running"
                run.coro_started = True
                async with observing_operations(observer):
                    result = await coro
            except asyncio.CancelledError:
                if not run.coro_started:
                    coro.close()
                job = self._jobs.get(job_id)
                if job is not None and job["status"] not in TERMINAL_JOB_STATUSES:
                    if run.write_granted:
                        self._finish(
                            job_id,
                            "error",
                            error="The job was cancelled while running; its change may have reached the controller.",
                        )
                    else:
                        self._finish(job_id, "cancelled")
                    logger.info("Background job %s cancelled", job_id)
                raise
            except Exception as e:
                self._finish(job_id, "error", error=str(e))
                logger.error("Background job %s failed with error: %s", job_id, e, exc_info=True)
            else:
                self._finish(job_id, "done", result=result)
                logger.info("Background job %s completed successfully", job_id)
            finally:
                # Whatever happened, a later job chained to this one may go.
                run.admitted.set()

        # Keep a reference until the task finishes: the event loop holds only
        # a weak one, and an unreferenced task can be collected mid-flight.
        task = asyncio.create_task(_runner(), name=f"unifi-job-{job_id}")
        run.task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        return job_id

    async def wait_admitted(self, job_id: str) -> None:
        """Return once the job has joined a controller gate, or finished.

        Returns at once for an unknown or finished job.
        """
        run = self._runs.get(job_id)
        if run is not None:
            await run.admitted.wait()

    async def cancel(self, job_id: str) -> Dict[str, Any]:
        """Cancel a job that has not started its controller change yet.

        A ``queued`` job (waiting for an earlier job, or for its write turn)
        is withdrawn and marked ``cancelled``; nothing is sent to the
        controller. A running job is refused: a change already sent cannot be
        recalled. A finished or unknown job is reported as it is.

        Returns:
            ``{"jobId", "cancelled": bool, "status"}``, plus ``"reason"`` when
            the job was not cancelled.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return {"jobId": job_id, "cancelled": False, "status": "unknown", "reason": "Unknown job."}
        status = job["status"]
        if status in TERMINAL_JOB_STATUSES:
            return {"jobId": job_id, "cancelled": False, "status": status, "reason": "The job has already finished."}
        run = self._runs.get(job_id)
        if status != "queued" or run is None:
            return {
                "jobId": job_id,
                "cancelled": False,
                "status": status,
                "reason": "The job is already running; a change sent to the controller cannot be recalled.",
            }
        task = run.task
        if not run.coro_started:
            # The runner may never get to run (a task cancelled before its
            # first step skips its body), so close the coroutine here.
            run.coro.close()
        if task is not None:
            task.cancel()
        self._finish(job_id, "cancelled")
        logger.info("Background job %s cancelled while queued", job_id)
        return {"jobId": job_id, "cancelled": True, "status": "cancelled"}

    async def status(self, job_id: str) -> Dict[str, Any]:
        """Retrieve the current status of a job.

        Args:
            job_id: The unique identifier of the job to query

        Returns:
            A dictionary containing the job's state including:
            - status: 'queued', 'running', 'done', 'error', 'cancelled' or 'unknown'
            - started: Unix timestamp when the job started (if known)
            - completed: Unix timestamp when the job finished (if finished)
            - result: The return value of the job (if completed successfully)
            - error: Error message (if failed)
            - position: Write operations ahead of it (only while queued;
              ``None`` while it waits for an earlier job)
        """
        async with self._lock:
            self._prune_locked(self._clock())
            if job_id not in self._jobs:
                logger.warning("Status requested for unknown job ID: %s", job_id)
                return {"status": "unknown"}

            # Return a copy to prevent external modifications
            status = dict(self._jobs[job_id])
            if status["status"] == "queued":
                run = self._runs.get(job_id)
                ticket = run.ticket if run is not None else None
                status["position"] = ticket.position if ticket is not None and ticket.waiting else None
            return status


# Global singleton instance
JOBS = JobStore()


async def start_async_tool(
    handler: Callable[..., Coroutine[Any, Any, Dict[str, Any]]],
    args: Dict[str, Any],
    *,
    after: str | None = None,
) -> Dict[str, Any]:
    """Start a tool handler as a background job.

    Wraps a tool handler function in a background job and returns the job ID
    for later status checking. This allows long-running operations to be
    executed asynchronously without blocking the MCP server.

    Args:
        handler: The async function to execute (typically a tool handler)
        args: Dictionary of arguments to pass to the handler
        after: Start the handler only once this earlier job is admitted
            (see :meth:`JobStore.start`)

    Returns:
        A dictionary containing the job ID: {"jobId": "abc123def456"}
    """
    try:
        # Create a coroutine by calling the handler with unpacked args
        coro = handler(**args)
        job_id = await JOBS.start(coro, after=after)
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


async def cancel_job(job_id: str) -> Dict[str, Any]:
    """Cancel a queued background job; a convenience wrapper around JobStore.cancel()."""
    return await JOBS.cancel(job_id)
