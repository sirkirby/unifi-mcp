#!/usr/bin/env python3
"""Example: Using batch operations for parallel/async execution.

This demonstrates how to use unifi_batch for parallel operations and
unifi_batch_status to check their progress.

Usage:
    python examples/python/use_async_jobs.py
"""

import asyncio
import json
import time
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def execute_tool(session: ClientSession, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a single tool synchronously using unifi_execute."""
    result = await session.call_tool("unifi_execute", arguments={"tool": tool_name, "arguments": arguments})

    # Extract result from response
    content = result.content[0].text if hasattr(result, "content") else result
    if isinstance(content, str):
        content = json.loads(content)

    return content


async def start_batch(session: ClientSession, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Start multiple operations in parallel using unifi_batch."""
    result = await session.call_tool("unifi_batch", arguments={"operations": operations})

    # Extract response
    content = result.content[0].text if hasattr(result, "content") else result
    if isinstance(content, str):
        content = json.loads(content)

    return content


async def check_batch_status(session: ClientSession, job_ids: List[str]) -> Dict[str, Any]:
    """Check the status of multiple batch jobs."""
    result = await session.call_tool("unifi_batch_status", arguments={"jobIds": job_ids})

    # Extract status from result
    content = result.content[0].text if hasattr(result, "content") else result
    if isinstance(content, str):
        content = json.loads(content)

    return content


async def wait_for_batch(
    session: ClientSession, job_ids: List[str], timeout: int = 60, poll_interval: float = 1.0
) -> Dict[str, Any]:
    """Wait for all batch jobs to complete, polling periodically."""
    start_time = time.time()

    while time.time() - start_time < timeout:
        status = await check_batch_status(session, job_ids)

        # Check if all jobs are complete
        all_done = all(job.get("status") in ["done", "error"] for job in status.get("jobs", []))

        if all_done:
            return status

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"Batch jobs did not complete within {timeout}s")


async def main():
    """Main function demonstrating batch execution."""
    print("=" * 70)
    print("UniFi Network MCP - Batch Operations Example")
    print("=" * 70)
    print()

    server_params = StdioServerParameters(
        command="unifi-network-mcp",
        args=["--stdio"],
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Example 1: Single synchronous execution
            print("Example 1: Single tool execution with unifi_execute")
            print("-" * 70)

            try:
                print("Calling unifi_execute with unifi_list_clients...")
                result = await execute_tool(session, "unifi_list_clients", {"limit": 5})
                print("Result received!")
                print(f"  Preview: {str(result)[:100]}...")
            except Exception as e:
                print(f"Error: {e}")

            print()
            print()

            # Example 2: Batch parallel execution
            print("Example 2: Parallel execution with unifi_batch")
            print("-" * 70)

            try:
                # Start multiple operations in parallel
                operations = [
                    {"tool": "unifi_list_clients", "arguments": {"limit": 3}},
                    {"tool": "unifi_list_devices", "arguments": {}},
                    {"tool": "unifi_get_system_info", "arguments": {}},
                ]

                print(f"Starting batch with {len(operations)} operations...")
                batch_result = await start_batch(session, operations)

                if batch_result.get("errors"):
                    print(f"Some operations failed to start: {batch_result['errors']}")

                job_ids = [job["jobId"] for job in batch_result.get("jobs", [])]
                print(f"Started {len(job_ids)} jobs: {job_ids}")
                print()

                # Poll for completion
                print("Polling batch status...")
                for i in range(10):
                    await asyncio.sleep(0.5)
                    status = await check_batch_status(session, job_ids)

                    completed = sum(1 for job in status.get("jobs", []) if job.get("status") in ["done", "error"])
                    print(f"  [{i + 1}] Completed: {completed}/{len(job_ids)}")

                    if completed == len(job_ids):
                        print()
                        print("All jobs completed!")
                        for job in status.get("jobs", []):
                            status_str = job.get("status")
                            if status_str == "done":
                                print(f"  {job['jobId']}: {str(job.get('result', {}))[:60]}...")
                            else:
                                print(f"  {job['jobId']}: ERROR - {job.get('error')}")
                        break

            except Exception as e:
                print(f"Error: {e}")

            print()
            print()

            # Example 3: Workflow explanation
            print("Example 3: Complete batch workflow")
            print("-" * 70)
            print("""
This example shows how you would use batch operations for:

  - Bulk client operations (get details for multiple clients)
  - Parallel device queries (check status of many devices)
  - Bulk configuration changes (update multiple settings)

Workflow:
  1. Call unifi_tool_index to discover available tools
  2. Use unifi_execute for single operations (returns result directly)
  3. Use unifi_batch for parallel operations (returns job IDs)
  4. Poll with unifi_batch_status until all jobs complete
  5. Process results or handle errors

Benefits:
  - Parallel execution - run multiple operations simultaneously
  - Non-blocking - check status anytime
  - Error isolation - individual job failures don't affect others
  - Efficient - reduces round-trips for bulk operations
            """)

            print("=" * 70)
            print("Examples complete!")
            print()
            print("Next steps:")
            print("  - Use unifi_execute for most single operations")
            print("  - Use unifi_batch for bulk/parallel operations")
            print("  - Build pipelines combining tool discovery and execution")
            print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n Fatal error: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
