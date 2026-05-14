"""Cross-layer symmetry: every mutable field on a pydantic domain model
in unifi_core.<server>.models.<domain> must exist on the matching
Strawberry type in unifi_api.graphql.types.<server>.<domain> with a
compatible annotation.

The registry below names every (server, domain) pair that participates
in the test. Phase 0 seeds it with one pair (network/acl). Phase 1
adds Protect pairs; Phase 2 adds Access pairs.
"""

from __future__ import annotations

import importlib

import pytest
from _cross_layer_helpers import compare_pair

REGISTERED_PAIRS: list[tuple[str, str, str]] = [
    # (server, domain, pydantic_class_name)
    ("network", "acl", "AclRule"),
    ("network", "ap_group", "ApGroup"),
    ("network", "client_group", "ClientGroup"),
    ("network", "client_group", "UserGroup"),
    ("network", "content_filter", "ContentFilter"),
    ("network", "dns", "DnsRecord"),
    ("network", "firewall", "FirewallRule"),
    ("network", "firewall", "FirewallGroup"),
    ("network", "firewall", "FirewallZone"),
    ("network", "networks", "Network"),
    ("network", "oon", "OonPolicy"),
    ("network", "port_forwards", "PortForward"),
    ("network", "switch", "PortProfile"),
    ("network", "qos", "QosRule"),
    ("network", "traffic_routes", "TrafficRoute"),
    ("network", "route", "Route"),
    ("network", "route", "ActiveRoute"),
    ("network", "vpn", "VpnClient"),
    ("network", "vpn", "VpnServer"),
    ("network", "wlans", "Wlan"),
    ("network", "devices", "Device"),
    ("network", "devices", "DeviceRadio"),
    ("network", "system", "SnmpSettings"),
    ("network", "system", "AutoBackupSettings"),
    ("network", "system", "SystemInfo"),
    ("network", "system", "NetworkHealth"),
    ("network", "system", "Alarm"),
    ("network", "system", "Backup"),
    ("network", "system", "SiteSettings"),
    ("network", "system", "EventTypes"),
    ("network", "system", "TopClient"),
    ("network", "system", "SpeedtestResult"),
    ("network", "clients", "Client"),
    ("network", "clients", "BlockedClient"),
    ("network", "clients", "ClientLookup"),
    ("network", "events", "EventLog"),
    ("network", "sessions", "ClientSession"),
    ("network", "sessions", "ClientWifiDetails"),
    ("network", "stats", "StatPoint"),
    ("network", "stats", "DpiStats"),
    ("network", "vouchers", "Voucher"),
    ("network", "dpi", "DpiApplication"),
    ("network", "dpi", "DpiCategory"),
    ("protect", "cameras", "Camera"),
    ("protect", "lights", "Light"),
    ("protect", "chimes", "Chime"),
    ("protect", "sensors", "Sensor"),
    ("protect", "liveviews", "Liveview"),
    ("protect", "recordings", "Recording"),
    ("protect", "recordings", "RecordingStatusList"),
    ("protect", "events", "Event"),
    ("protect", "events", "SmartDetection"),
    ("protect", "events", "EventThumbnail"),
    ("protect", "alarms", "AlarmStatus"),
    ("protect", "alarms", "AlarmProfile"),
    ("protect", "alarms", "AlarmProfileList"),
    ("protect", "system", "ProtectSystemInfo"),
    ("protect", "system", "ProtectHealth"),
    ("protect", "system", "FirmwareStatus"),
    ("protect", "system", "Viewer"),
    ("protect", "system", "ViewerList"),
    ("access", "doors", "Door"),
    ("access", "doors", "DoorGroup"),
    ("access", "doors", "DoorStatus"),
    ("access", "credentials", "Credential"),
    ("access", "visitors", "Visitor"),
    ("access", "policies", "Policy"),
    ("access", "schedules", "Schedule"),
    ("access", "devices", "AccessDevice"),
    ("access", "users", "User"),
    ("access", "events", "Event"),
    ("access", "events", "ActivitySummary"),
    ("access", "system", "AccessSystemInfo"),
    ("access", "system", "AccessHealth"),
]


@pytest.mark.parametrize("server,domain,pydantic_name", REGISTERED_PAIRS)
def test_cross_layer_symmetry(server: str, domain: str, pydantic_name: str) -> None:
    pydantic_mod = importlib.import_module(f"unifi_core.{server}.models.{domain}")
    strawberry_mod = importlib.import_module(f"unifi_api.graphql.types.{server}.{domain}")

    pydantic_cls = getattr(pydantic_mod, pydantic_name)
    strawberry_cls = getattr(strawberry_mod, pydantic_name)
    # Prefer a per-class field set (e.g. USERGROUP_MUTABLE_FIELDS for UserGroup)
    # before falling back to the module-level MUTABLE_FIELDS.
    per_class_key = f"{pydantic_name.upper()}_MUTABLE_FIELDS"
    mutable_fields = getattr(pydantic_mod, per_class_key, None)
    if mutable_fields is None:
        mutable_fields = getattr(pydantic_mod, "MUTABLE_FIELDS")

    errors = compare_pair(pydantic_cls, mutable_fields, strawberry_cls)
    assert not errors, f"\nCross-layer drift in {server}/{domain}:\n  - " + "\n  - ".join(errors)
