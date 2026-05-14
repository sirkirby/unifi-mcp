"""Network serializer unit tests — one fixture per resource."""

from unifi_api.serializers._registry import (
    discover_serializers,
    serializer_registry_singleton,
)


def _registry():
    """Trigger discovery once for the test module."""
    discover_serializers(manifest_tool_names=set())  # validate_manifest can be no-op for tests
    return serializer_registry_singleton()


def test_client_serializer_shape() -> None:
    """Phase 6 PR2 Task 19 — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.network.client import Client

    sample_raw = {
        "mac": "aa:bb:cc:dd:ee:ff",
        "last_ip": "10.0.0.5",
        "hostname": "laptop",
        "is_wired": False,
        "is_guest": False,
        "is_online": True,
        "last_seen": 1700000000,
        "first_seen": 1600000000,
    }

    class FakeClient:
        raw = sample_raw

    out = Client.from_manager_output(FakeClient()).to_dict()
    assert out["mac"] == "aa:bb:cc:dd:ee:ff"
    assert out["ip"] == "10.0.0.5"
    assert out["hostname"] == "laptop"
    assert out["is_wired"] is False
    assert out["status"] == "online"


def test_device_serializer_shape() -> None:
    """Phase 6 PR2 Task 20 — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.network.device import Device

    sample_raw = {
        "mac": "11:22:33:44:55:66",
        "name": "AP1",
        "model": "U6-Pro",
        "type": "uap",
        "version": "6.5.59",
        "uptime": 3600,
        "state": 1,
    }

    class FakeDevice:
        raw = sample_raw

    out = Device.from_manager_output(FakeDevice()).to_dict()
    assert out["mac"] == "11:22:33:44:55:66"
    assert out["name"] == "AP1"
    assert out["model"] == "U6-Pro"
    assert out["state"] == "connected"


def test_network_serializer_shape() -> None:
    """Phase 6 PR2 Task 21 — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.network.network import Network

    class FakeNetwork:
        raw = {
            "_id": "net1",
            "name": "Default",
            "purpose": "corporate",
            "enabled": True,
        }

    out = Network.from_manager_output(FakeNetwork()).to_dict()
    assert out["id"] == "net1"
    assert out["name"] == "Default"
    assert out["purpose"] == "corporate"
    assert out["enabled"] is True


def test_firewall_rule_serializer_shape() -> None:
    """Phase 6 PR2 Task 22 — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.network.firewall import FirewallRule

    class FakeRule:
        raw = {
            "_id": "rule1",
            "name": "Block IoT",
            "action": "BLOCK",
            "enabled": True,
            "predefined": False,
        }

    out = FirewallRule.from_manager_output(FakeRule()).to_dict()
    assert out["id"] == "rule1"
    assert out["name"] == "Block IoT"
    assert out["action"] == "BLOCK"


def test_wlan_serializer_shape() -> None:
    """Phase 6 PR2 Task 21 — projection moved to a Strawberry type. Same dict
    shape contract as the old serializer; verified via Type.to_dict()."""
    from unifi_api.graphql.types.network.wlan import Wlan

    class FakeWlan:
        raw = {
            "_id": "wlan1",
            "name": "MyWiFi",
            "enabled": True,
            "security": "wpapsk",
        }

    out = Wlan.from_manager_output(FakeWlan()).to_dict()
    assert out["id"] == "wlan1"
    assert out["name"] == "MyWiFi"
    assert out["security"] == "wpapsk"
    assert out["enabled"] is True
