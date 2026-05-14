#!/usr/bin/env python3
"""Example: Query the UniFi Network MCP tool index.

This demonstrates how to programmatically discover available tools
and their schemas using the tool index API.

Usage:
    python examples/python/query_tool_index.py
"""

import asyncio
import json
from typing import Any, Dict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def query_tool_index() -> Dict[str, Any]:
    """Connect to the MCP server and query the tool index."""
    server_params = StdioServerParameters(
        command="unifi-network-mcp",
        args=["--stdio"],
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Query the tool index with full schemas
            result = await session.call_tool("unifi_tool_index", arguments={"include_schemas": True})
            return result


async def main():
    """Main function demonstrating tool index usage."""
    print("=" * 70)
    print("UniFi Network MCP - Tool Index Query Example")
    print("=" * 70)
    print()

    try:
        # Query the tool index
        print("Querying tool index...")
        result = await query_tool_index()

        # Extract tools
        tools = result.content[0].text if hasattr(result, "content") else result
        if isinstance(tools, str):
            tools = json.loads(tools)

        tool_list = tools.get("tools", [])

        print(f"✓ Found {len(tool_list)} tools")
        print()

        # Group tools by category
        categories = {}
        for tool in tool_list:
            name = tool.get("name", "")
            # Extract category from tool name (e.g., "unifi_list_clients" -> "clients")
            if name.startswith("unifi_"):
                parts = name.replace("unifi_", "").split("_")
                category = parts[-1] if len(parts) > 1 else "other"

                if category not in categories:
                    categories[category] = []
                categories[category].append(tool)

        # Display tools by category
        print("Available Tools by Category:")
        print("-" * 70)

        for category in sorted(categories.keys()):
            print(f"\n{category.upper()}:")
            for tool in categories[category]:
                name = tool.get("name", "")
                description = tool.get("description", "No description")
                print(f"  • {name}")
                print(f"    {description[:80]}...")

        print()
        print("-" * 70)

        # Show a detailed example
        if tool_list:
            print("\nExample Tool Detail (unifi_list_clients):")
            print("-" * 70)

            example_tool = next((t for t in tool_list if t["name"] == "unifi_list_clients"), tool_list[0])

            print(json.dumps(example_tool, indent=2))

        print()
        print("✓ Tool index query complete!")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
