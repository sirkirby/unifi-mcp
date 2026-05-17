"""MCP-native metadata helpers shared by UniFi MCP servers."""

from __future__ import annotations

import base64
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from typing import Any

from mcp.types import Icon

PROJECT_WEBSITE_URL = "https://github.com/sirkirby/unifi-mcp"
_ICON_SIZES = (48, 96, 192)
_ICON_FAMILIES = frozenset({"access", "network", "protect", "relay"})

_TITLE_WORDS = {
    "acl": "ACL",
    "api": "API",
    "dns": "DNS",
    "dpi": "DPI",
    "fastmcp": "FastMCP",
    "ip": "IP",
    "ips": "IPS",
    "mcp": "MCP",
    "oon": "OON",
    "pdu": "PDU",
    "ptz": "PTZ",
    "qos": "QoS",
    "rf": "RF",
    "snmp": "SNMP",
    "unifi": "UniFi",
    "vpn": "VPN",
    "wlan": "WLAN",
}

_TOOL_PREFIXES = ("unifi_", "protect_", "access_")

_ICON_CACHE: dict[str, tuple[Icon, ...]] = {}


def tool_title_from_name(name: str) -> str:
    """Derive a human-readable MCP tool title from a stable programmatic name."""
    stem = name
    for prefix in _TOOL_PREFIXES:
        if stem.startswith(prefix):
            stem = stem.removeprefix(prefix)
            break
    return " ".join(_TITLE_WORDS.get(part, part.capitalize()) for part in stem.split("_") if part)


def mcp_icons_for_server(family: str) -> list[Icon]:
    """Return packaged PNG icon data URIs for an MCP server or relay client.

    The decoded set is cached because each call would otherwise re-read and
    base64-encode three PNGs from package resources.
    """
    if family not in _ICON_FAMILIES:
        allowed = ", ".join(sorted(_ICON_FAMILIES))
        raise ValueError(f"Unknown MCP icon family {family!r}. Expected one of: {allowed}")

    cached = _ICON_CACHE.get(family)
    if cached is None:
        icon_dir = files("unifi_mcp_shared").joinpath("assets", "icons")
        decoded: list[Icon] = []
        for size in _ICON_SIZES:
            icon_path = icon_dir.joinpath(f"{family}-{size}.png")
            encoded = base64.b64encode(icon_path.read_bytes()).decode("ascii")
            decoded.append(
                Icon(
                    src=f"data:image/png;base64,{encoded}",
                    mimeType="image/png",
                    sizes=[f"{size}x{size}"],
                )
            )
        cached = tuple(decoded)
        _ICON_CACHE[family] = cached
    return list(cached)


def configure_mcp_server_metadata(
    server: Any,
    *,
    package_name: str,
    website_url: str = PROJECT_WEBSITE_URL,
    icon_family: str | None = None,
) -> None:
    """Attach app package metadata to FastMCP's underlying initialize response."""
    mcp_server = getattr(server, "_mcp_server", None)
    if mcp_server is None:
        return

    mcp_server.website_url = website_url
    if icon_family is not None:
        mcp_server.icons = mcp_icons_for_server(icon_family)
    try:
        mcp_server.version = version(package_name)
    except PackageNotFoundError:  # pragma: no cover - package is installed in workspace tests
        pass
