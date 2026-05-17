"""Reusable assertion helpers for MCP server integration tests."""

from __future__ import annotations

import base64
from importlib.metadata import version
from typing import Any

from unifi_mcp_shared.metadata import PROJECT_WEBSITE_URL


def assert_server_initialization_metadata(server: Any, *, package_name: str) -> None:
    """Assert that ``server`` exposes the expected MCP initialization metadata.

    Each app's integration test invokes this with its own FastMCP server
    instance so the project-wide initialize-response contract is asserted in
    exactly one place.
    """
    options = server._mcp_server.create_initialization_options()
    assert options.server_name == package_name
    assert options.server_version == version(package_name)
    assert options.website_url == PROJECT_WEBSITE_URL
    assert options.icons is not None
    assert [icon.sizes for icon in options.icons] == [["48x48"], ["96x96"], ["192x192"]]
    assert {icon.mimeType for icon in options.icons} == {"image/png"}
    decoded = base64.b64decode(options.icons[0].src.removeprefix("data:image/png;base64,"))
    assert decoded.startswith(b"\x89PNG\r\n\x1a\n")
