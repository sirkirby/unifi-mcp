"""DPI catalog tools fail visibly when the integration API cannot answer.

Without a Network API key the integration API is unreachable, and an empty
catalog reported as success reads as "this controller has no DPI apps".
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from unifi_core.network.managers.dpi_manager import DpiManager

HOST = "controller-host-sentinel.example"


def _manager_without_key() -> DpiManager:
    connection = MagicMock()
    connection.host = HOST
    connection.port = 443
    connection.site = "default"
    connection.tls_env_prefix = "NETWORK"
    connection.get_cached = MagicMock(return_value=None)
    auth = MagicMock()
    auth.has_api_key = False
    return DpiManager(connection, auth)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "prefix"),
    [
        ("list_dpi_categories", "Failed to list DPI categories: "),
        ("list_dpi_applications", "Failed to list DPI applications: "),
    ],
)
async def test_missing_api_key_is_a_failure_naming_the_setting(monkeypatch, tool_name, prefix):
    from unifi_network_mcp.tools import dpi

    monkeypatch.setattr(dpi, "dpi_manager", _manager_without_key())

    result = await getattr(dpi, tool_name)()

    assert result["success"] is False
    assert result["error"].startswith(prefix)
    assert "UNIFI_NETWORK_API_KEY" in result["error"]
    assert HOST not in result["error"]
    assert "count" not in result
