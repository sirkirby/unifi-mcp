#!/usr/bin/env python3
"""Smoke test MCP server metadata over the real stdio transport.

This validates the MCP protocol surface without invoking any UniFi tools:
``initialize`` for server metadata and ``tools/list`` for tool titles.
"""

from __future__ import annotations

import argparse
import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROJECT_WEBSITE_URL = "https://github.com/sirkirby/unifi-mcp"
REPO_ROOT = Path(__file__).resolve().parent.parent


class MetadataSmokeError(AssertionError):
    """Raised when MCP metadata does not match the expected contract."""


@dataclass(frozen=True)
class ServerSpec:
    package: str
    command: str
    expected_name: str
    index_tool: str
    expected_index_title: str


SERVER_SPECS = {
    "network": ServerSpec(
        package="unifi-network-mcp",
        command="unifi-network-mcp",
        expected_name="unifi-network-mcp",
        index_tool="unifi_tool_index",
        expected_index_title="UniFi Network Tool Index",
    ),
    "protect": ServerSpec(
        package="unifi-protect-mcp",
        command="unifi-protect-mcp",
        expected_name="unifi-protect-mcp",
        index_tool="protect_tool_index",
        expected_index_title="UniFi Protect Tool Index",
    ),
    "access": ServerSpec(
        package="unifi-access-mcp",
        command="unifi-access-mcp",
        expected_name="unifi-access-mcp",
        index_tool="access_tool_index",
        expected_index_title="UniFi Access Tool Index",
    ),
}

EXPECTED_ICON_SIZES = [["48x48"], ["96x96"], ["192x192"]]
OFFLINE_SERVER_NAMES = ("network", "protect")


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def validate_icons(icons: list[Any] | None, *, label: str) -> None:
    """Validate that MCP icons are PNG data URIs at the expected sizes."""
    if icons is None:
        raise MetadataSmokeError(f"{label}: missing icons")
    if len(icons) != 3:
        raise MetadataSmokeError(f"{label}: expected 3 icons, got {len(icons)}")

    sizes = [_field(icon, "sizes") for icon in icons]
    if sizes != EXPECTED_ICON_SIZES:
        raise MetadataSmokeError(f"{label}: expected icon sizes {EXPECTED_ICON_SIZES}, got {sizes}")

    mime_types = {_field(icon, "mimeType") for icon in icons}
    if mime_types != {"image/png"}:
        raise MetadataSmokeError(f"{label}: expected image/png icons, got {sorted(mime_types)}")

    prefix = "data:image/png;base64,"
    for icon in icons:
        src = _field(icon, "src")
        if not isinstance(src, str) or not src.startswith(prefix):
            raise MetadataSmokeError(f"{label}: icon src is not a PNG data URI")
        data = base64.b64decode(src.removeprefix(prefix))
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise MetadataSmokeError(f"{label}: icon src is not PNG data")


def validate_server_metadata(spec: ServerSpec, server_info: Any) -> None:
    """Validate initialize.serverInfo metadata."""
    name = _field(server_info, "name")
    if name != spec.expected_name:
        raise MetadataSmokeError(f"{spec.expected_name}: expected server name {spec.expected_name!r}, got {name!r}")

    website_url = _field(server_info, "websiteUrl")
    if website_url != PROJECT_WEBSITE_URL:
        raise MetadataSmokeError(
            f"{spec.expected_name}: expected websiteUrl {PROJECT_WEBSITE_URL!r}, got {website_url!r}"
        )

    version = _field(server_info, "version")
    if not version:
        raise MetadataSmokeError(f"{spec.expected_name}: missing server version")

    validate_icons(_field(server_info, "icons"), label=spec.expected_name)


def validate_tool_titles(spec: ServerSpec, tools: list[Any]) -> None:
    """Validate tools/list includes the expected meta-tool title."""
    by_name = {_field(tool, "name"): tool for tool in tools}
    tool = by_name.get(spec.index_tool)
    if tool is None:
        raise MetadataSmokeError(f"{spec.expected_name}: missing {spec.index_tool} in tools/list")

    title = _field(tool, "title")
    if title != spec.expected_index_title:
        raise MetadataSmokeError(
            f"{spec.expected_name}: {spec.index_tool} expected title {spec.expected_index_title!r}, got {title!r}"
        )


def smoke_env(*, use_current_env: bool = False) -> dict[str, str]:
    """Build the environment used by the metadata smoke server subprocesses."""
    env = os.environ.copy()
    if not use_current_env:
        env.update(
            {
                "UNIFI_HOST": "127.0.0.1",
                "UNIFI_USERNAME": "metadata-smoke",
                "UNIFI_PASSWORD": "metadata-smoke",
                "UNIFI_API_KEY": "metadata-smoke",
                "UNIFI_ACCESS_API_KEY": "metadata-smoke",
                "UNIFI_NETWORK_HOST": "127.0.0.1",
                "UNIFI_NETWORK_USERNAME": "metadata-smoke",
                "UNIFI_NETWORK_PASSWORD": "metadata-smoke",
                "UNIFI_NETWORK_API_KEY": "metadata-smoke",
                "UNIFI_PROTECT_HOST": "127.0.0.1",
                "UNIFI_PROTECT_USERNAME": "metadata-smoke",
                "UNIFI_PROTECT_PASSWORD": "metadata-smoke",
                "UNIFI_PROTECT_API_KEY": "metadata-smoke",
                "UNIFI_ACCESS_HOST": "127.0.0.1",
                "UNIFI_ACCESS_USERNAME": "metadata-smoke",
                "UNIFI_ACCESS_PASSWORD": "metadata-smoke",
            }
        )
    env["UNIFI_MCP_HTTP_ENABLED"] = "false"
    return env


def selected_server_names(*, server: str, use_current_env: bool) -> list[str]:
    """Return the servers that can be smoke-tested for this invocation."""
    if server != "all":
        if server == "access" and not use_current_env:
            raise MetadataSmokeError(
                "access metadata smoke requires --use-current-env; the Access server exits when controller "
                "initialization fails, so it cannot run against offline dummy credentials yet"
            )
        return [server]

    if use_current_env:
        return list(SERVER_SPECS)
    return list(OFFLINE_SERVER_NAMES)


async def smoke_server(spec: ServerSpec, *, use_current_env: bool = False) -> str:
    """Run the stdio MCP smoke for one server and return a one-line summary."""
    env = smoke_env(use_current_env=use_current_env)

    params = StdioServerParameters(
        command="uv",
        args=["run", "--package", spec.package, spec.command],
        cwd=REPO_ROOT,
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            validate_server_metadata(spec, init.serverInfo)

            tools_result = await session.list_tools()
            validate_tool_titles(spec, tools_result.tools)

            return (
                f"{spec.expected_name} "
                f"{init.serverInfo.version} "
                f"{spec.expected_index_title} "
                f"icons={len(init.serverInfo.icons or [])}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server",
        choices=[*SERVER_SPECS.keys(), "all"],
        default="all",
        help=(
            "Server to smoke test. Defaults to all offline-compatible servers "
            "(network, protect), or all servers with --use-current-env."
        ),
    )
    parser.add_argument(
        "--use-current-env",
        action="store_true",
        help="Use the current controller environment instead of offline dummy credentials.",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    server_names = selected_server_names(server=args.server, use_current_env=args.use_current_env)
    for server_name in server_names:
        print(await smoke_server(SERVER_SPECS[server_name], use_current_env=args.use_current_env))


def main() -> None:
    anyio.run(main_async)


if __name__ == "__main__":
    main()
