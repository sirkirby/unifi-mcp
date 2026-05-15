"""Tests for MCP-native metadata helpers."""

from __future__ import annotations

import base64

from mcp.server.fastmcp import FastMCP
from unifi_mcp_shared.metadata import (
    PROJECT_WEBSITE_URL,
    configure_mcp_server_metadata,
    mcp_icons_for_server,
    tool_title_from_name,
)


def _decode_icon_src(src: str) -> bytes:
    prefix = "data:image/png;base64,"
    assert src.startswith(prefix)
    return base64.b64decode(src.removeprefix(prefix))


def test_tool_title_from_name_preserves_known_acronyms() -> None:
    assert tool_title_from_name("unifi_get_ips_events") == "Get IPS Events"
    assert tool_title_from_name("protect_ptz_move") == "PTZ Move"


def test_mcp_icons_for_server_returns_packaged_png_data_uris() -> None:
    icons = mcp_icons_for_server("network")

    assert [icon.sizes for icon in icons] == [["48x48"], ["96x96"], ["192x192"]]
    assert {icon.mimeType for icon in icons} == {"image/png"}
    for icon in icons:
        data = _decode_icon_src(icon.src)
        assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_mcp_icons_for_server_rejects_unknown_server() -> None:
    try:
        mcp_icons_for_server("unknown")
    except ValueError as exc:
        assert "Unknown MCP icon family" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected ValueError")


def test_configure_mcp_server_metadata_attaches_icons() -> None:
    server = FastMCP("test-server")

    configure_mcp_server_metadata(server, package_name="unifi-mcp-shared", icon_family="access")

    options = server._mcp_server.create_initialization_options()
    assert options.website_url == PROJECT_WEBSITE_URL
    assert options.icons is not None
    assert options.icons[0].sizes == ["48x48"]
    assert _decode_icon_src(options.icons[0].src).startswith(b"\x89PNG\r\n\x1a\n")
