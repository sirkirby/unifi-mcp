"""The largest evidence documents the default collection budgets allow.

Both are collected by the real collectors through the SDKs' own decoders,
with only the HTTP exchange replaced: a busy Network event log that fills the
events budget, and Protect with the most camera sources a request accepts.
Rows imitate live shapes (24-hex IDs, several named stations per event, long
messages) with synthetic, locally administered identifiers.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from unifi_core.incident_collection import MAX_MAPPINGS
from unifi_core.incident_evidence import IncidentEvidence, parse_utc
from unifi_core.network.incident_collection import collect_network_incident_evidence
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
from unifi_core.protect.incident_collection import collect_protect_incident_evidence
from unifi_core.protect.models.incident_evidence import MAX_CAMERA_IDS, ProtectIncidentRequest

from .network.sdk_transport import paging_event_manager
from .protect.sdk_transport import sdk_protect_event_manager

NOW = parse_utc("2026-08-09T12:05:00.000000Z")
WINDOW = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-09T12:00:00Z", "location_id": "fixture-location-a"}
_START_MS = 1786190400000
_SPAN_MS = 86_400_000

_NETWORK_TEMPLATES = (
    (
        "CLIENT_ROAMED",
        "CLIENT_DEVICES",
        "{CLIENT} roamed from {AP_FROM} (channel 36, -71 dBm) to {AP_TO} (channel 149, -58 dBm).",
        ("CLIENT", "AP_FROM", "AP_TO"),
    ),
    (
        "TRAFFIC_BLOCKED_KNOWN_SOURCE_CLIENT",
        "SECURITY",
        "{SRC_CLIENT} was blocked from accessing {DST_IP} by the {TRIGGER} Firewall Policy.",
        ("SRC_CLIENT", "DST_IP", "TRIGGER"),
    ),
    (
        "DEVICE_DISCONNECTED_SW",
        "UNIFI_DEVICES",
        "{DEVICE} disconnected from {UPLINK} on port 12 after 3 missed informs.",
        ("DEVICE", "UPLINK"),
    ),
    (
        "CLIENT_CONNECTED_WIRED",
        "CLIENT_DEVICES",
        "{CLIENT} connected to {SW} on port 7 (VLAN fixture-iot, 1 Gbps full duplex).",
        ("CLIENT", "SW"),
    ),
)


CAMERAS = [f"66b5c0{camera:018x}" for camera in range(MAX_CAMERA_IDS)]


def _mac(group: int, index: int) -> str:
    return f"02:00:{group:02x}:{(index >> 8) & 0xFF:02x}:{index & 0xFF:02x}:{(index * 7) & 0xFF:02x}"


def _network_row(index: int) -> dict:
    key, category, message, names = _NETWORK_TEMPLATES[index % len(_NETWORK_TEMPLATES)]
    parameters = {}
    for slot, name in enumerate(names):
        if name == "DST_IP":
            parameters[name] = {"id": "198.51.100.24", "name": "198.51.100.24"}
        elif name == "TRIGGER":
            parameters[name] = {"id": f"{index:024x}", "name": "fixture-policy-block-iot-to-lan"}
        else:
            parameters[name] = {
                "id": _mac(slot + 1, index),
                "name": f"fixture-{name.lower()}-{index:04d}",
                "hostname": f"fixture-host-{index:04d}",
            }
    return {
        "id": f"66b4{index:020x}",
        "key": key,
        "category": category,
        "subcategory": "CLIENT_CONNECTIVITY",
        "event": key,
        "severity": "MEDIUM",
        "timestamp": _START_MS + (index * 53_731) % _SPAN_MS,
        "message_raw": message,
        "title_raw": "Fixture Event",
        "parameters": parameters,
        "type": "CLIENT_ACTIVITY",
    }


def _mappings() -> list[dict]:
    """The most assertions a request accepts: a switch mapped to every camera in both directions,
    as the investigation skill asserts them, and stations mapped to a location."""
    device = {"kind": "network_device", "id_kind": "mac", "id": _mac(4, 7)}
    location = {"kind": "location", "id_kind": "location_id", "id": "fixture-location-a"}
    assertions = []
    for camera in CAMERAS:
        target = {"kind": "camera", "id_kind": "protect_camera_id", "id": camera}
        assertions.append({"entity": device, "target": target, "source": "product_inventory"})
        assertions.append({"entity": target, "target": device, "source": "product_inventory"})
    index = 0
    while len(assertions) < MAX_MAPPINGS:
        station = {"kind": "network_client", "id_kind": "mac", "id": _mac(1, index)}
        assertions.append({"entity": station, "target": location, "source": "operator_input"})
        index += 1
    return assertions


async def network_worst_case() -> IncidentEvidence:
    """A busy site log read at default budgets until the events budget is spent."""
    rows = sorted((_network_row(i) for i in range(2_500)), key=lambda row: -row["timestamp"])
    manager = paging_event_manager(rows)
    request = NetworkIncidentRequest(**WINDOW, mappings=_mappings())
    with patch("unifi_core.network.managers.event_manager.time.time", return_value=NOW.timestamp()):
        return await collect_network_incident_evidence(manager, request, site="default", now=lambda: NOW)


def _protect_page(camera: int, page: int, size: int) -> list[dict]:
    rows = []
    for index in range(page * 100, page * 100 + size):
        start = _START_MS + ((camera * 997 + index * 86_311) % _SPAN_MS)
        rows.append(
            {
                "id": f"66b5{camera:04x}{index:016x}",
                "type": "smartDetectZone" if index % 2 else "motion",
                "camera": CAMERAS[camera],
                "start": start,
                "end": start + 12_500,
                "score": 87,
                "smartDetectTypes": ["person", "vehicle"] if index % 2 else [],
            }
        )
    return sorted(rows, key=lambda row: -row["start"])


async def protect_worst_case() -> IncidentEvidence:
    """Every camera a request accepts, each read in two pages: partial, since no snapshot spans reads."""
    pages = [_protect_page(camera, page, 100 - page) for camera in range(MAX_CAMERA_IDS) for page in (0, 1)]
    manager = sdk_protect_event_manager(*pages)
    request = ProtectIncidentRequest(**WINDOW, camera_ids=CAMERAS, mappings=_mappings())
    return await collect_protect_incident_evidence(manager, request, now=lambda: NOW + timedelta(0))
