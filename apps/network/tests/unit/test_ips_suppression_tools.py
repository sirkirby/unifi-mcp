"""Unit tests for the unifi_list_ips_suppressions MCP tool."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.network.models.ips_suppression import ips_suppressions_from_controller


@pytest.fixture
def manager(monkeypatch):
    from unifi_network_mcp.tools import system

    mock = MagicMock()
    mock._connection.site = "branch"
    mock.list_ips_suppressions = AsyncMock(
        return_value=ips_suppressions_from_controller(
            {
                "alerts": [
                    {
                        "id": 2000001,
                        "gid": 1,
                        "type": "track",
                        "category": "emerging-scan",
                        "signature": "ET TEST Example signature",
                        "tracking": [{"mode": "ip", "value": "192.0.2.10", "direction": "src"}],
                    }
                ],
                "whitelist": [],
            }
        )
    )
    monkeypatch.setattr(system, "system_manager", mock)
    return mock


@pytest.mark.asyncio
async def test_list_ips_suppressions(manager):
    from unifi_network_mcp.tools.system import list_ips_suppressions

    assert await list_ips_suppressions() == {
        "success": True,
        "site": "branch",
        "count": 1,
        "suppressions": [
            {
                "signature_id": 2000001,
                "gid": 1,
                "signature": "ET TEST Example signature",
                "category": "emerging-scan",
                "suppression_type": "track",
                "scope": "source",
                "direction": "src",
                "mode": "ip",
                "target": "192.0.2.10",
            }
        ],
        "exclusions": [],
    }


@pytest.mark.asyncio
async def test_failure_is_not_an_empty_list(manager, caplog):
    from unifi_network_mcp.tools.system import list_ips_suppressions

    manager.list_ips_suppressions.side_effect = RuntimeError("private controller text")
    assert await list_ips_suppressions() == {"success": False, "error": "Failed to list IPS suppressions"}
    assert "private controller text" not in caplog.text


def test_annotations():
    from unifi_network_mcp.runtime import server
    from unifi_network_mcp.tools import system  # noqa: F401 - decorator registration

    tool = server._tool_manager._tools["unifi_list_ips_suppressions"]
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is False
