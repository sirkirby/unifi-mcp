"""MCP server metadata exposed during initialization."""

from __future__ import annotations

import base64
import os
from importlib.metadata import version

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


def test_server_initialization_metadata() -> None:
    from unifi_protect_mcp.runtime import server

    options = server._mcp_server.create_initialization_options()
    assert options.server_name == "unifi-protect-mcp"
    assert options.server_version == version("unifi-protect-mcp")
    assert options.website_url == "https://github.com/sirkirby/unifi-mcp"
    assert options.icons is not None
    assert [icon.sizes for icon in options.icons] == [["48x48"], ["96x96"], ["192x192"]]
    assert {icon.mimeType for icon in options.icons} == {"image/png"}
    assert base64.b64decode(options.icons[0].src.removeprefix("data:image/png;base64,")).startswith(
        b"\x89PNG\r\n\x1a\n"
    )
