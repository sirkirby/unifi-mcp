"""Port validation at the Core firewall create boundary."""

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.firewall_manager import FirewallManager


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["source", "destination"])
@pytest.mark.parametrize(
    "endpoint",
    [
        {"ports": ["445"]},
        {"port_matching_type": "SPECIFIC"},
        {"port_matching_type": "SPECIFIC", "port": 445},
        {"port_matching_type": "SPECIFIC", "port": ["445"]},
        {"port_matching_type": "SPECIFIC", "port": ""},
        {"port_matching_type": "SPECIFIC", "port": " "},
    ],
)
async def test_invalid_ports_fail_before_controller_connection(direction, endpoint):
    connection = MagicMock()
    connection.ensure_connected = AsyncMock()
    connection.request = AsyncMock()
    manager = FirewallManager(connection)

    with pytest.raises(ValueError, match=rf"{direction}\.port"):
        await manager.create_firewall_policy({direction: endpoint})

    connection.ensure_connected.assert_not_awaited()
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_ports_reach_controller_without_mutating_input():
    data = {
        "name": "Specific ports",
        "action": "ALLOW",
        "enabled": False,
        "source": {"port_matching_type": "SPECIFIC", "port": "445"},
        "destination": {"port_matching_type": "SPECIFIC", "port": "8443"},
    }
    before = copy.deepcopy(data)
    connection = MagicMock()
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(return_value={"_id": "created-policy", **data})

    created = await FirewallManager(connection).create_firewall_policy(data)

    connection.request.assert_awaited_once()
    assert connection.request.call_args.args[0].data == before
    assert created.raw["source"]["port"] == "445"
    assert created.raw["destination"]["port"] == "8443"
    assert data == before
