"""One controller connection attempt at a time, with bounded waits for callers.

MCP servers answer ``initialize`` before they reach the controller, so the
connection is made in the background while the client is already calling
tools. Every connection manager runs its start-up connect and its on-demand
reconnects through a :class:`ConnectAttempt`: a second caller joins the
attempt that is already running instead of starting another, and a tool call
waits for it only within a fixed window from the attempt's start. A controller
that does not answer within that window costs each call one bounded wait at
most, while the attempt itself carries on in the background.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# How long a caller waits for an attempt, counted from the attempt's start. A
# healthy controller connects well within it; a call made after the window
# fails at once with a "still connecting" error rather than waiting again.
CONNECT_WAIT_SECONDS = 15.0


class ConnectAttempt:
    """Run at most one connection attempt at a time and let callers wait on it."""

    def __init__(
        self,
        *,
        wait_seconds: float = CONNECT_WAIT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.wait_seconds = wait_seconds
        self._clock = clock
        self._task: asyncio.Task[bool] | None = None
        self._started_at = 0.0

    @property
    def in_progress(self) -> bool:
        """True while an attempt is running."""
        return self._task is not None and not self._task.done()

    def start(self, connect: Callable[[], Awaitable[bool]], *, name: str) -> asyncio.Task[bool]:
        """Start ``connect`` unless an attempt is already running; return the running attempt.

        A failure the attempt raises is logged by class and reported as ``False``.
        """
        if self._task is not None and not self._task.done():
            return self._task
        self._started_at = self._clock()
        self._task = asyncio.get_running_loop().create_task(self._run(connect), name=name)
        return self._task

    @staticmethod
    async def _run(connect: Callable[[], Awaitable[bool]]) -> bool:
        try:
            return bool(await connect())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Class only: SDK and transport messages can carry controller text.
            logger.error("Controller connection attempt failed: %s", type(exc).__name__)
            return False

    async def join(self) -> bool:
        """Wait for the running attempt to finish; ``False`` when none ran or it was cancelled.

        Cancelling the caller does not cancel the attempt.
        """
        task = self._task
        if task is None:
            return False
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                return False
            raise

    async def wait(self) -> bool | None:
        """Wait for the running attempt within the window from its start.

        Returns the attempt's result, or ``None`` when it is still running at
        the end of the window. Never cancels the attempt.
        """
        task = self._task
        if task is None:
            return None
        if not task.done():
            remaining = self._started_at + self.wait_seconds - self._clock()
            if remaining > 0:
                await asyncio.wait({task}, timeout=remaining)
            if not task.done():
                return None
        if task.cancelled():
            return False
        return task.result()

    async def cancel(self) -> None:
        """Cancel a running attempt and wait for it to unwind."""
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
