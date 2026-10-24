"""Tests for the async jobs framework.

This module tests the JobStore class and helper functions for managing
background jobs in the UniFi Network MCP server.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from unifi_network_mcp.jobs import JobStore, get_job_status, start_async_tool


class TestJobStore:
    """Tests for the JobStore class."""

    @pytest.mark.asyncio
    async def test_start_and_complete_job(self):
        """Test starting a job that completes successfully."""
        store = JobStore()

        async def simple_task():
            await asyncio.sleep(0.01)
            return {"success": True, "message": "Task completed"}

        job_id = await store.start(simple_task())

        # Job should exist and be running
        assert len(job_id) == 16  # 8 bytes = 16 hex chars
        status = await store.status(job_id)
        assert status["status"] == "running"
        assert "started" in status

        # Wait for completion
        await asyncio.sleep(0.05)

        # Job should be done with result
        status = await store.status(job_id)
        assert status["status"] == "done"
        assert status["result"]["success"] is True
        assert "completed" in status

    @pytest.mark.asyncio
    async def test_job_with_error(self):
        """Test starting a job that raises an exception."""
        store = JobStore()

        async def failing_task():
            await asyncio.sleep(0.01)
            raise ValueError("Intentional test error")

        job_id = await store.start(failing_task())

        # Wait for it to fail
        await asyncio.sleep(0.05)

        # Job should have error status
        status = await store.status(job_id)
        assert status["status"] == "error"
        assert "Intentional test error" in status["error"]
        assert "completed" in status


class TestHelperFunctions:
    """Tests for the helper functions."""

    @pytest.mark.asyncio
    async def test_start_async_tool(self):
        """Test the start_async_tool helper function."""

        async def mock_handler(**kwargs):
            await asyncio.sleep(0.01)
            return {"success": True, "args": kwargs}

        result = await start_async_tool(mock_handler, {"arg1": "value1"})

        assert "jobId" in result
        job_id = result["jobId"]

        # Wait for completion
        await asyncio.sleep(0.05)

        # Verify job completed
        status = await get_job_status(job_id)
        assert status["status"] == "done"
        assert status["result"]["success"] is True
        assert status["result"]["args"]["arg1"] == "value1"
