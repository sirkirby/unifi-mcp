#!/usr/bin/env python3
"""Smoke test MCP standard surfaces over the real stdio transport.

This validates the MCP protocol surface without invoking any UniFi tools:
``initialize`` for server metadata and ``tools/list`` for tool metadata across
the supported registration modes.
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
from unifi_mcp_shared.metadata import PROJECT_WEBSITE_URL
from unifi_mcp_shared.protocol import DEFAULT_MCP_PROTOCOL_REVISION

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRATION_MODES = ("lazy", "eager", "meta_only")


class MetadataSmokeError(AssertionError):
    """Raised when MCP metadata does not match the expected contract."""


@dataclass(frozen=True)
class ServerSpec:
    package: str
    command: str
    expected_name: str
    prefix: str
    index_tool: str
    expected_index_title: str
    representative_tool: str


SERVER_SPECS = {
    "network": ServerSpec(
        package="unifi-network-mcp",
        command="unifi-network-mcp",
        expected_name="unifi-network-mcp",
        prefix="unifi",
        index_tool="unifi_tool_index",
        expected_index_title="UniFi Network Tool Index",
        representative_tool="unifi_list_clients",
    ),
    "protect": ServerSpec(
        package="unifi-protect-mcp",
        command="unifi-protect-mcp",
        expected_name="unifi-protect-mcp",
        prefix="protect",
        index_tool="protect_tool_index",
        expected_index_title="UniFi Protect Tool Index",
        representative_tool="protect_list_cameras",
    ),
    "access": ServerSpec(
        package="unifi-access-mcp",
        command="unifi-access-mcp",
        expected_name="unifi-access-mcp",
        prefix="access",
        index_tool="access_tool_index",
        expected_index_title="UniFi Access Tool Index",
        representative_tool="access_list_doors",
    ),
}

EXPECTED_ICON_SIZES = [["48x48"], ["96x96"], ["192x192"]]
OFFLINE_SERVER_NAMES = ("network", "protect")


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _tool_by_name(tools: list[Any]) -> dict[str, Any]:
    return {_field(tool, "name"): tool for tool in tools}


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


def validate_initialize_result(spec: ServerSpec, init: Any) -> None:
    """Validate initialize negotiation and server metadata."""
    protocol_version = _field(init, "protocolVersion")
    if protocol_version != DEFAULT_MCP_PROTOCOL_REVISION:
        raise MetadataSmokeError(
            f"{spec.expected_name}: expected protocolVersion {DEFAULT_MCP_PROTOCOL_REVISION!r}, "
            f"got {protocol_version!r}"
        )

    capabilities = _field(init, "capabilities")
    tools_capability = _field(capabilities, "tools")
    if tools_capability is None:
        raise MetadataSmokeError(f"{spec.expected_name}: initialize result did not advertise tools capability")

    validate_server_metadata(spec, init.serverInfo)


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


def validate_tool_schema(tool: Any, *, label: str) -> None:
    """Validate standard MCP Tool fields that must always be present."""
    input_schema = _field(tool, "inputSchema")
    if not isinstance(input_schema, dict):
        raise MetadataSmokeError(f"{label}: missing inputSchema")
    if input_schema.get("type") != "object":
        raise MetadataSmokeError(f"{label}: expected object inputSchema, got {input_schema!r}")

    description = _field(tool, "description")
    if not description:
        raise MetadataSmokeError(f"{label}: missing description")


def validate_meta_tool_surface(spec: ServerSpec, tools: list[Any]) -> None:
    """Validate tools/list includes the expected compatibility meta-tools."""
    by_name = _tool_by_name(tools)
    tool = by_name.get(spec.index_tool)
    if tool is None:
        raise MetadataSmokeError(f"{spec.expected_name}: missing {spec.index_tool} in tools/list")

    title = _field(tool, "title")
    if title != spec.expected_index_title:
        raise MetadataSmokeError(
            f"{spec.expected_name}: {spec.index_tool} expected title {spec.expected_index_title!r}, got {title!r}"
        )

    validate_tool_schema(tool, label=f"{spec.expected_name}:{spec.index_tool}")
    annotations = _field(tool, "annotations")
    if _field(annotations, "readOnlyHint") is not True or _field(annotations, "openWorldHint") is not False:
        raise MetadataSmokeError(f"{spec.expected_name}: {spec.index_tool} missing read-only closed-world annotations")

    required_meta_tools = {
        spec.index_tool,
        f"{spec.prefix}_execute",
        f"{spec.prefix}_batch",
        f"{spec.prefix}_batch_status",
    }
    missing = sorted(required_meta_tools - set(by_name))
    if missing:
        raise MetadataSmokeError(f"{spec.expected_name}: missing meta-tools in tools/list: {missing}")


def validate_mode_tools(spec: ServerSpec, tools: list[Any], *, registration_mode: str) -> None:
    """Validate registration-mode-specific standard tools/list behavior."""
    by_name = _tool_by_name(tools)
    load_tool_name = f"{spec.prefix}_load_tools"
    representative = by_name.get(spec.representative_tool)
    load_tool = by_name.get(load_tool_name)

    if registration_mode == "lazy":
        if load_tool is None:
            raise MetadataSmokeError(f"{spec.expected_name}: lazy mode missing {load_tool_name}")
        validate_tool_schema(load_tool, label=f"{spec.expected_name}:{load_tool_name}")
        annotations = _field(load_tool, "annotations")
        if _field(annotations, "idempotentHint") is not True or _field(annotations, "openWorldHint") is not False:
            raise MetadataSmokeError(
                f"{spec.expected_name}: {load_tool_name} missing idempotent closed-world annotations"
            )
        if "notifications/tools/list_changed" not in (_field(load_tool, "description") or ""):
            raise MetadataSmokeError(f"{spec.expected_name}: {load_tool_name} does not document list_changed refresh")
        if representative is not None:
            raise MetadataSmokeError(
                f"{spec.expected_name}: lazy mode should not expose {spec.representative_tool} before loading"
            )
        return

    if registration_mode == "meta_only":
        if load_tool is not None:
            raise MetadataSmokeError(f"{spec.expected_name}: meta_only mode should not expose {load_tool_name}")
        if representative is not None:
            raise MetadataSmokeError(
                f"{spec.expected_name}: meta_only mode should not expose {spec.representative_tool} directly"
            )
        return

    if registration_mode == "eager":
        if load_tool is not None:
            raise MetadataSmokeError(f"{spec.expected_name}: eager mode should not expose {load_tool_name}")
        if representative is None:
            raise MetadataSmokeError(f"{spec.expected_name}: eager mode missing {spec.representative_tool}")
        validate_tool_schema(representative, label=f"{spec.expected_name}:{spec.representative_tool}")
        annotations = _field(representative, "annotations")
        if _field(annotations, "openWorldHint") is not False:
            raise MetadataSmokeError(
                f"{spec.expected_name}: {spec.representative_tool} missing closed-world annotation"
            )
        output_schema = _field(representative, "outputSchema")
        if not isinstance(output_schema, dict):
            raise MetadataSmokeError(f"{spec.expected_name}: {spec.representative_tool} missing outputSchema")
        if not {"success", "data", "error"}.issubset(output_schema.get("properties", {})):
            raise MetadataSmokeError(
                f"{spec.expected_name}: {spec.representative_tool} outputSchema does not describe UniFi response"
            )
        return

    raise MetadataSmokeError(f"Unknown registration mode: {registration_mode}")


def smoke_env(*, registration_mode: str, use_current_env: bool = False) -> dict[str, str]:
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
    env["UNIFI_TOOL_REGISTRATION_MODE"] = registration_mode
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


async def smoke_server(spec: ServerSpec, *, registration_mode: str, use_current_env: bool = False) -> str:
    """Run the stdio MCP smoke for one server and return a one-line summary."""
    env = smoke_env(registration_mode=registration_mode, use_current_env=use_current_env)

    params = StdioServerParameters(
        command="uv",
        args=["run", "--package", spec.package, spec.command],
        cwd=REPO_ROOT,
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            validate_initialize_result(spec, init)

            tools_result = await session.list_tools()
            validate_meta_tool_surface(spec, tools_result.tools)
            validate_mode_tools(spec, tools_result.tools, registration_mode=registration_mode)

            return (
                f"{spec.expected_name} "
                f"mode={registration_mode} "
                f"{init.serverInfo.version} "
                f"{spec.expected_index_title} "
                f"tools={len(tools_result.tools)} "
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
    parser.add_argument(
        "--registration-mode",
        choices=[*REGISTRATION_MODES, "all"],
        default="lazy",
        help="Registration mode to smoke test. Use 'all' to cover lazy, eager, and meta_only.",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    server_names = selected_server_names(server=args.server, use_current_env=args.use_current_env)
    registration_modes = list(REGISTRATION_MODES) if args.registration_mode == "all" else [args.registration_mode]
    for server_name in server_names:
        for registration_mode in registration_modes:
            print(
                await smoke_server(
                    SERVER_SPECS[server_name],
                    registration_mode=registration_mode,
                    use_current_env=args.use_current_env,
                )
            )


def main() -> None:
    anyio.run(main_async)


if __name__ == "__main__":
    main()
