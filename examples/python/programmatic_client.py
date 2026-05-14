#!/usr/bin/env python3
"""Example: Programmatic MCP client for UniFi operations.

This demonstrates how to build a custom Python client that uses the
UniFi Network MCP server programmatically without LLM involvement.

Usage:
    python examples/python/programmatic_client.py
"""

import asyncio
import json
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class UniFiMCPClient:
    """A simple programmatic client for UniFi Network MCP server."""

    def __init__(self):
        """Initialize the client."""
        self.session = None
        self._context = None

    async def __aenter__(self):
        """Connect to the MCP server."""
        server_params = StdioServerParameters(
            command="unifi-network-mcp",
            args=["--stdio"],
            env=None,
        )

        self._context = stdio_client(server_params)
        read, write = await self._context.__aenter__()

        self.session = ClientSession(read, write)
        await self.session.__aenter__()
        await self.session.initialize()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Disconnect from the MCP server."""
        if self.session:
            await self.session.__aexit__(exc_type, exc_val, exc_tb)
        if self._context:
            await self._context.__aexit__(exc_type, exc_val, exc_tb)

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool and return the result."""
        result = await self.session.call_tool(name, arguments=arguments)

        # Extract content from result
        content = result.content[0].text if hasattr(result, "content") else result

        # Try to parse as JSON
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content

        return content

    async def list_clients(self, limit: int = None) -> List[Dict[str, Any]]:
        """List network clients."""
        args = {}
        if limit is not None:
            args["limit"] = limit

        result = await self.call_tool("unifi_list_clients", args)
        return result.get("clients", []) if isinstance(result, dict) else []

    async def get_client_details(self, mac_address: str) -> Dict[str, Any]:
        """Get details for a specific client."""
        return await self.call_tool("unifi_get_client_details", {"mac_address": mac_address})

    async def get_network_stats(self) -> Dict[str, Any]:
        """Get network statistics."""
        return await self.call_tool("unifi_get_network_stats", {})

    async def list_devices(self) -> List[Dict[str, Any]]:
        """List UniFi devices."""
        result = await self.call_tool("unifi_list_devices", {})
        return result.get("devices", []) if isinstance(result, dict) else []

    async def get_top_clients(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top clients by traffic."""
        result = await self.call_tool("unifi_get_top_clients", {"limit": limit})
        return result.get("clients", []) if isinstance(result, dict) else []


async def main():
    """Main function demonstrating programmatic client usage."""
    print("=" * 70)
    print("UniFi Network MCP - Programmatic Client Example")
    print("=" * 70)
    print()

    async with UniFiMCPClient() as client:
        # Example 1: Get network statistics
        print("Example 1: Network Statistics")
        print("-" * 70)
        try:
            stats = await client.get_network_stats()
            print("✓ Retrieved network stats")
            print(f"  Preview: {str(stats)[:200]}...")
        except Exception as e:
            print(f"✗ Error: {e}")
        print()

        # Example 2: List devices
        print("Example 2: List Devices")
        print("-" * 70)
        try:
            devices = await client.list_devices()
            print(f"✓ Found {len(devices)} devices")

            for device in devices[:5]:  # Show first 5
                name = device.get("name", "Unknown")
                model = device.get("model", "Unknown")
                ip = device.get("ip", "Unknown")
                print(f"  • {name} ({model}) - {ip}")

            if len(devices) > 5:
                print(f"  ... and {len(devices) - 5} more")
        except Exception as e:
            print(f"✗ Error: {e}")
        print()

        # Example 3: Get top clients
        print("Example 3: Top Clients by Traffic")
        print("-" * 70)
        try:
            top_clients = await client.get_top_clients(limit=5)
            print(f"✓ Retrieved top {len(top_clients)} clients")

            for i, client_data in enumerate(top_clients, 1):
                name = client_data.get("name") or client_data.get("hostname") or client_data.get("mac", "Unknown")
                tx = client_data.get("tx_bytes", 0)
                rx = client_data.get("rx_bytes", 0)
                total = tx + rx

                # Convert to human-readable
                total_mb = total / (1024 * 1024)
                print(f"  {i}. {name}: {total_mb:.2f} MB")

        except Exception as e:
            print(f"✗ Error: {e}")
        print()

        # Example 4: Process data in Python
        print("Example 4: Data Processing in Python")
        print("-" * 70)
        print("""
The key benefit of programmatic access is processing data in code:

  • Filter large result sets before displaying
  • Transform data into custom formats
  • Combine multiple tool calls into complex workflows
  • Build dashboards and reports
  • Automate network management tasks

Example workflow:
  1. Get all clients
  2. Filter by connection type (wireless/wired)
  3. Sort by traffic
  4. Generate a summary report
  5. Export to CSV/JSON

All without sending massive datasets through an LLM!
        """)

    print("=" * 70)
    print("✓ Examples complete!")
    print()
    print("Next steps:")
    print("  • Build custom network analysis scripts")
    print("  • Create automated monitoring tools")
    print("  • Integrate with other systems (Grafana, InfluxDB, etc.)")
    print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
