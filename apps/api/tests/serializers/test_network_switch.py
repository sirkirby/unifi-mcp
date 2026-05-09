"""Switch + device cluster serializer unit tests (Phase 4A PR1 Cluster 1)."""

from unifi_api.serializers._registry import (
    serializer_registry_singleton,
    discover_serializers,
)


def _registry():
    discover_serializers(manifest_tool_names=set())
    return serializer_registry_singleton()


# ---- switch.py ----


def test_port_profile_list_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.switch import PortProfile

    sample = {
        "_id": "pp1",
        "name": "All-Tagged",
        "native_networkconf_id": "net1",
        "tagged_networkconf_ids": ["net2"],
        "poe_mode": "auto",
        "isolation": False,
    }
    out = PortProfile.from_manager_output(sample).to_dict()
    assert out["id"] == "pp1"
    assert out["name"] == "All-Tagged"
    assert out["poe_mode"] == "auto"
    assert out["tagged_networkconf_ids"] == ["net2"]
    assert PortProfile.render_hint("list")["kind"] == "list"


def test_port_profile_detail_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.switch import PortProfile

    sample = {"_id": "pp2", "name": "Voice", "poe_mode": "passive"}
    out = PortProfile.from_manager_output(sample).to_dict()
    assert out["id"] == "pp2"
    assert out["name"] == "Voice"
    assert PortProfile.render_hint("detail")["kind"] == "detail"


def test_switch_ports_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry wrapper-dict type."""
    from unifi_api.graphql.types.network.switch import SwitchPorts

    sample = {
        "name": "USW-24",
        "model": "US24P250",
        "port_overrides": [
            {"port_idx": 1, "name": "Trunk", "portconf_id": "pp1", "poe_mode": "auto"},
            {"port_idx": 2, "name": "Voice", "portconf_id": "pp2"},
        ],
    }
    data = SwitchPorts.from_manager_output(sample).to_dict()
    assert data["name"] == "USW-24"
    assert len(data["port_overrides"]) == 2
    assert data["port_overrides"][0]["port_idx"] == 1
    assert SwitchPorts.render_hint("detail")["kind"] == "detail"


def test_port_stats_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry wrapper-dict type."""
    from unifi_api.graphql.types.network.switch import PortStats

    sample = {
        "name": "USW-24",
        "model": "US24P250",
        "port_table": [
            {
                "port_idx": 1,
                "tx_bytes": 1000,
                "rx_bytes": 2000,
                "tx_packets": 5,
                "rx_packets": 10,
                "speed": 1000,
                "enable": True,
            }
        ],
    }
    data = PortStats.from_manager_output(sample).to_dict()
    assert data["name"] == "USW-24"
    assert data["port_table"][0]["tx_bytes"] == 1000
    assert PortStats.render_hint("detail")["kind"] == "detail"


def test_switch_capabilities_serializer_shape() -> None:
    """Phase 6 PR2 Task 24 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.switch import SwitchCapabilities

    sample = {
        "name": "USW-24",
        "model": "US24P250",
        "switch_caps": {"max_aggregate_sessions": 8, "max_mirror_sessions": 1},
        "stp_version": "rstp",
        "stp_priority": "32768",
        "jumboframe_enabled": False,
    }
    data = SwitchCapabilities.from_manager_output(sample).to_dict()
    assert data["name"] == "USW-24"
    assert data["stp_version"] == "rstp"
    assert data["jumboframe_enabled"] is False
    assert SwitchCapabilities.render_hint("detail")["kind"] == "detail"


def test_switch_mutation_ack_bool() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("unifi_update_switch_stp")
    out = s.serialize_action(True, tool_name="unifi_update_switch_stp")
    assert out["success"] is True
    assert out["data"] == {"success": True}
    assert out["render_hint"]["kind"] == "detail"


def test_switch_mutation_ack_dict_passthrough() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("unifi_create_port_profile")
    out = s.serialize_action({"_id": "pp9", "name": "New"}, tool_name="unifi_create_port_profile")
    assert out["success"] is True
    assert out["data"]["_id"] == "pp9"
    assert out["render_hint"]["kind"] == "detail"


# ---- devices.py extensions ----


def test_device_radio_serializer_shape() -> None:
    """Phase 6 PR2 Task 20 — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.network.device import DeviceRadio

    sample = {
        "mac": "11:22:33:44:55:66",
        "name": "AP1",
        "model": "U6-Pro",
        "radios": [
            {"name": "wifi0", "radio": "ng", "channel": 6, "tx_power": 17, "ht": 20},
            {"name": "wifi1", "radio": "na", "channel": 36, "tx_power": 23, "ht": 80},
        ],
    }
    data = DeviceRadio.from_manager_output(sample).to_dict()
    assert data["mac"] == "11:22:33:44:55:66"
    assert len(data["radios"]) == 2
    assert DeviceRadio.render_hint("detail")["kind"] == "detail"


def test_lldp_neighbors_serializer_shape() -> None:
    """Phase 6 PR2 Task 20 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.device import LldpNeighbors

    sample = {
        "name": "USW-24",
        "model": "US24P250",
        "lldp_table": [
            {
                "local_port_idx": 1,
                "chassis_id": "aa:bb:cc:dd:ee:ff",
                "port_id": "Gi1/0/1",
                "system_name": "neighbor-sw",
                "capabilities": ["bridge"],
            }
        ],
    }
    data = LldpNeighbors.from_manager_output(sample).to_dict()
    assert data["lldp_table"][0]["chassis_id"] == "aa:bb:cc:dd:ee:ff"
    assert LldpNeighbors.render_hint("detail")["kind"] == "detail"


def test_rogue_ap_serializer_shape() -> None:
    """Projection moved to a Strawberry type. ``is_known`` is hardcoded
    to False — the controller no longer surfaces a separate
    known/acknowledged rogue classification."""
    from unifi_api.graphql.types.network.device import RogueAp

    sample = {
        "bssid": "aa:bb:cc:11:22:33",
        "essid": "EvilTwin",
        "channel": 11,
        "rssi": -55,
        "last_seen": 1700000000,
        "is_rogue": True,
    }
    out_unknown = RogueAp.from_manager_output(sample).to_dict()
    assert out_unknown["bssid"] == "aa:bb:cc:11:22:33"
    assert out_unknown["ssid"] == "EvilTwin"
    assert out_unknown["is_known"] is False
    assert RogueAp.render_hint("list")["kind"] == "list"


def test_rf_scan_result_serializer_shape() -> None:
    """Phase 6 PR2 Task 20 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.device import RfScanResult

    sample = {
        "bssid": "aa:bb:cc:11:22:33",
        "essid": "Neighbor",
        "channel": 6,
        "rssi": -70,
        "ts": 1700000000,
    }
    data = RfScanResult.from_manager_output(sample).to_dict()
    assert data["bssid"] == "aa:bb:cc:11:22:33"
    assert data["channel"] == 6
    assert RfScanResult.render_hint("list")["kind"] == "list"


def test_available_channel_serializer_shape() -> None:
    """Phase 6 PR2 Task 20 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.device import AvailableChannel

    sample = {"channel": 36, "freq": 5180, "ht": 80, "allowed": True}
    data = AvailableChannel.from_manager_output(sample).to_dict()
    assert data["channel"] == 36
    assert data["frequency_mhz"] == 5180
    assert data["width_mhz"] == 80
    assert AvailableChannel.render_hint("list")["kind"] == "list"


def test_speedtest_status_serializer_shape() -> None:
    """Phase 6 PR2 Task 20 — projection moved to a Strawberry type."""
    from unifi_api.graphql.types.network.device import SpeedtestStatus

    sample = {
        "status_download": 500.5,
        "status_upload": 50.1,
        "latency": 12,
        "rundate": 1700000000,
        "status": 0,
    }
    data = SpeedtestStatus.from_manager_output(sample).to_dict()
    assert data["download_mbps"] == 500.5
    assert data["upload_mbps"] == 50.1
    assert data["latency_ms"] == 12
    assert SpeedtestStatus.render_hint("detail")["kind"] == "detail"


def test_device_mutation_ack_bool() -> None:
    reg = _registry()
    s = reg.serializer_for_tool("unifi_reboot_device")
    out = s.serialize_action(True, tool_name="unifi_reboot_device")
    assert out["success"] is True
    assert out["data"] == {"success": True}
    assert out["render_hint"]["kind"] == "detail"


def test_device_mutation_ack_dispatches_for_all_mutations() -> None:
    """Every mutation tool registered should resolve via the registry."""
    reg = _registry()
    for tool in (
        "unifi_adopt_device",
        "unifi_force_provision_device",
        "unifi_locate_device",
        "unifi_reboot_device",
        "unifi_rename_device",
        "unifi_set_device_led",
        "unifi_set_site_leds",
        "unifi_toggle_device",
        "unifi_trigger_rf_scan",
        "unifi_trigger_speedtest",
        "unifi_update_device_radio",
        "unifi_upgrade_device",
        "unifi_create_port_profile",
        "unifi_update_port_profile",
        "unifi_delete_port_profile",
        "unifi_set_switch_port_profile",
        "unifi_configure_port_aggregation",
        "unifi_configure_port_mirror",
        "unifi_power_cycle_port",
        "unifi_set_jumbo_frames",
        "unifi_update_switch_stp",
    ):
        s = reg.serializer_for_tool(tool)
        out = s.serialize_action(True, tool_name=tool)
        assert out["render_hint"]["kind"] == "detail"
