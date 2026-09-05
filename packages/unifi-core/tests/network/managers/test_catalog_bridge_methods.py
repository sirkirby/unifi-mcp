"""Focused tests for Core methods exposed by the generated API action catalog."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.device_manager import DeviceManager
from unifi_core.network.managers.firewall_manager import FirewallManager
from unifi_core.network.managers.qos_manager import QosManager
from unifi_core.network.managers.stats_manager import StatsManager


@pytest.mark.asyncio
async def test_get_firewall_policy_by_id_returns_matching_policy() -> None:
    manager = FirewallManager(MagicMock())
    wanted = MagicMock(raw={"_id": "policy-2"})
    manager.get_firewall_policies = AsyncMock(return_value=[MagicMock(raw={"_id": "policy-1"}), wanted])

    assert await manager.get_firewall_policy_by_id("policy-2") is wanted
    manager.get_firewall_policies.assert_awaited_once_with(include_predefined=True)


@pytest.mark.asyncio
async def test_get_firewall_policy_by_id_raises_for_missing_policy() -> None:
    manager = FirewallManager(MagicMock())
    manager.get_firewall_policies = AsyncMock(return_value=[])

    with pytest.raises(UniFiNotFoundError):
        await manager.get_firewall_policy_by_id("missing")


@pytest.mark.asyncio
async def test_toggle_qos_rule_enabled_inverts_current_state_through_update_path() -> None:
    manager = QosManager(MagicMock())
    manager.get_qos_rule_details = AsyncMock(return_value={"_id": "qos-1", "enabled": False})
    manager.update_qos_rule = AsyncMock(return_value={"_id": "qos-1", "enabled": True})

    result = await manager.toggle_qos_rule_enabled("qos-1")

    assert result == {"_id": "qos-1", "enabled": True}
    manager.get_qos_rule_details.assert_awaited_once_with("qos-1")
    manager.update_qos_rule.assert_awaited_once_with("qos-1", {"enabled": True})


@pytest.mark.asyncio
async def test_toggle_qos_rule_enabled_defaults_missing_state_to_enabled() -> None:
    manager = QosManager(MagicMock())
    manager.get_qos_rule_details = AsyncMock(return_value={"_id": "qos-1"})
    manager.update_qos_rule = AsyncMock(return_value={"_id": "qos-1", "enabled": True})

    await manager.toggle_qos_rule_enabled("qos-1")

    manager.update_qos_rule.assert_awaited_once_with("qos-1", {"enabled": True})


@pytest.mark.asyncio
async def test_client_stats_bridge_resolves_controller_id_to_mac() -> None:
    client_manager = MagicMock()
    client_manager.get_client_details = AsyncMock(return_value=MagicMock(raw={"mac": "aa:bb:cc:dd:ee:ff"}))
    manager = StatsManager(MagicMock(), client_manager)
    manager.get_client_stats = AsyncMock(return_value=[{"rx_bytes": 1}])

    result = await manager.get_client_stats_for_identifier("client-object-id", duration_hours=24)

    assert result == [{"rx_bytes": 1}]
    client_manager.get_client_details.assert_awaited_once_with("client-object-id", existence_only=True)
    manager.get_client_stats.assert_awaited_once_with("aa:bb:cc:dd:ee:ff", duration_hours=24, granularity="hourly")


@pytest.mark.asyncio
async def test_device_stats_bridge_resolves_identifier_and_report_family(monkeypatch) -> None:
    device_manager = MagicMock()
    device_manager.get_device_details = AsyncMock(
        return_value=MagicMock(raw={"mac": "11:22:33:44:55:66", "type": "uap"})
    )
    monkeypatch.setattr(
        "unifi_core.network.managers.stats_manager.DeviceManager",
        MagicMock(return_value=device_manager),
    )
    manager = StatsManager(MagicMock(), MagicMock())
    manager.get_device_stats = AsyncMock(return_value=[{"num_sta": 2}])

    result = await manager.get_device_stats_for_identifier("device-object-id", duration_hours=168)

    assert result == [{"num_sta": 2}]
    device_manager.get_device_details.assert_awaited_once_with("device-object-id")
    manager.get_device_stats.assert_awaited_once_with(
        "11:22:33:44:55:66",
        duration_hours=168,
        granularity="hourly",
        device_type="ap",
    )


@pytest.mark.asyncio
async def test_set_outlet_state_rejects_non_relay_before_controller_write() -> None:
    connection = MagicMock()
    connection.request = AsyncMock()
    manager = DeviceManager(connection)
    manager.get_device_details = AsyncMock(
        return_value=MagicMock(
            raw={
                "_id": "pdu-1",
                "type": "usp",
                "outlet_table": [{"index": 1, "name": "USB", "has_relay": False}],
            }
        )
    )

    with pytest.raises(ValueError, match="does not have a controllable relay"):
        await manager.set_outlet_state("aa:bb:cc:dd:ee:ff", 1, False)

    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_outlet_state_rejects_nonpositive_index_before_lookup() -> None:
    manager = DeviceManager(MagicMock())
    manager.get_device_details = AsyncMock()

    with pytest.raises(ValueError, match="outlet_index must be >= 1"):
        await manager.set_outlet_state("aa:bb:cc:dd:ee:ff", 0, True)

    manager.get_device_details.assert_not_awaited()
