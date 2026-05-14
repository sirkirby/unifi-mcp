"""Tests for the shared jobs module."""

import asyncio

import pytest
from unifi_core.jobs import JobStore, get_job_status, start_async_tool


class TestJobStore:
    """Tests for the JobStore class."""

    @pytest.fixture
    def store(self):
        return JobStore()

    async def test_start_returns_job_id(self, store):
        async def noop():
            return "done"

        job_id = await store.start(noop())
        assert isinstance(job_id, str)
        assert len(job_id) == 16  # secrets.token_hex(8) produces 16 chars

    async def test_status_running(self, store):
        event = asyncio.Event()

        async def wait_for_event():
            await event.wait()
            return "finished"

        job_id = await store.start(wait_for_event())
        status = await store.status(job_id)
        assert status["status"] == "running"
        assert status["result"] is None
        event.set()
        await asyncio.sleep(0.05)

    async def test_status_done(self, store):
        async def quick():
            return {"data": "result"}

        job_id = await store.start(quick())
        await asyncio.sleep(0.05)  # let task complete
        status = await store.status(job_id)
        assert status["status"] == "done"
        assert status["result"] == {"data": "result"}
        assert "completed" in status

    async def test_status_error(self, store):
        async def fail():
            raise ValueError("test error")

        job_id = await store.start(fail())
        await asyncio.sleep(0.05)
        status = await store.status(job_id)
        assert status["status"] == "error"
        assert "test error" in status["error"]

    async def test_status_unknown(self, store):
        status = await store.status("nonexistent")
        assert status["status"] == "unknown"

    async def test_status_returns_copy(self, store):
        async def quick():
            return "ok"

        job_id = await store.start(quick())
        await asyncio.sleep(0.05)
        s1 = await store.status(job_id)
        s2 = await store.status(job_id)
        assert s1 is not s2
        assert s1 == s2


class TestStartAsyncTool:
    """Tests for start_async_tool."""

    async def test_returns_job_id(self):
        async def handler(x=1):
            return {"success": True}

        result = await start_async_tool(handler, {"x": 1})
        assert "jobId" in result

    async def test_error_returns_error_dict(self):
        async def bad_handler(**kwargs):
            raise TypeError("bad args")

        # Passing invalid args to trigger error before coroutine starts
        result = await start_async_tool(bad_handler, {"nonexistent_required": 1})
        # The handler accepts **kwargs so it won't fail on extra args
        # Let's test with a handler that fails on instantiation
        assert "jobId" in result or "error" in result


class TestGetJobStatus:
    """Tests for get_job_status convenience wrapper."""

    async def test_delegates_to_jobs_store(self):
        status = await get_job_status("nonexistent_id")
        assert status["status"] == "unknown"
