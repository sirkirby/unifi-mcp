"""Read models for Network 11 Matter / Thread inventory (V2 API).

Read-only. Shapes the two endpoints behind the Network UI's Settings > Matter
page, verified on Network 11.0.99:

- ``GET /thread-networks`` — detected Thread networks with their border routers
  and the Matter fabrics present on them.
- ``GET /matter/nodes``    — Matter nodes commissioned through the console.

Every public shape is an allowlist of controller fields. In particular a Matter
node's ``setup_code`` (its pairing code) and the border routers' fingerprint
internals are never copied. ``thread_client_id`` on a node is the controller
``id`` of the same device in the V2 active-client list (``MATTER_THREAD``
records), so the two inventories can be joined.

No create/update/delete tools exist (read-only); MUTABLE_FIELDS = frozenset().
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

MUTABLE_FIELDS: frozenset[str] = frozenset()


def _ro(description: str) -> Any:
    return Field(default=None, description=description, json_schema_extra={"mutable": False})


def _iso(value: Any) -> Optional[str]:
    """Epoch seconds (or milliseconds) to ISO 8601 UTC; None when not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = value / 1000 if value > 10_000_000_000 else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class ThreadBorderRouter(BaseModel):
    """A Thread border router the console has seen on the network."""

    name: Optional[str] = _ro("Border router name")
    model: Optional[str] = _ro("Model name")
    vendor: Optional[str] = _ro("Vendor name")
    mac: Optional[str] = _ro("Border router MAC address")
    ip: Optional[str] = _ro("Border router IP address")
    thread_version: Optional[str] = _ro("Thread version it advertises")
    network_name: Optional[str] = _ro("Thread network it belongs to")
    extended_address: Optional[str] = _ro("Thread extended address")
    reporter_mac: Optional[str] = _ro("MAC of the UniFi device that reported it")
    fresh: Optional[bool] = _ro("Whether the advertisement is current")
    first_seen: Optional[str] = _ro("First seen (ISO 8601 UTC)")
    last_seen: Optional[str] = _ro("Last seen (ISO 8601 UTC)")


class MatterFabric(BaseModel):
    """A Matter fabric (controller ecosystem) present on a Thread network."""

    label: Optional[str] = _ro("Fabric label")
    vendor_id: Optional[int] = _ro("Matter vendor ID of the fabric's controller")
    vendor_name: Optional[str] = _ro("Vendor name when the controller knows it")


class ThreadNetwork(BaseModel):
    """A Thread network detected by the console."""

    name: Optional[str] = _ro("Thread network name")
    extended_pan_id: Optional[str] = _ro("Extended PAN ID")
    channel: Optional[int] = _ro("IEEE 802.15.4 channel")
    device_count: Optional[int] = _ro("Thread devices the controller counts on this network")
    controller: Optional[str] = _ro("Ecosystem that manages the network (e.g. HOME_ASSISTANT)")
    border_routers: list[ThreadBorderRouter] = Field(
        default_factory=list, description="Border routers on this network", json_schema_extra={"mutable": False}
    )
    fabrics: list[MatterFabric] = Field(
        default_factory=list, description="Matter fabrics on this network", json_schema_extra={"mutable": False}
    )
    last_seen: Optional[str] = _ro("Last seen (ISO 8601 UTC)")


class MatterNode(BaseModel):
    """A Matter node commissioned through the console (never its setup code)."""

    node_id: Optional[int] = _ro("Matter node ID")
    name: Optional[str] = _ro("Display name")
    device_name: Optional[str] = _ro("Device name reported by the node")
    status: Optional[str] = _ro("Commissioning status (e.g. COMMISSIONED)")
    controller: Optional[str] = _ro("Ecosystem the node was commissioned into")
    channel: Optional[int] = _ro("Thread channel")
    thread_client_id: Optional[str] = _ro(
        "Controller id of the same device in the Thread client list (filter_type='thread')"
    )
    has_identify: Optional[bool] = _ro("Whether the node supports Identify")
    error_code: Optional[str] = _ro("Commissioning error code, when commissioning failed")
    created_at: Optional[str] = _ro("Commissioning requested (ISO 8601 UTC)")
    finished_at: Optional[str] = _ro("Commissioning finished (ISO 8601 UTC)")


def thread_border_router_from_controller(raw: Any) -> ThreadBorderRouter:
    raw = raw if isinstance(raw, dict) else {}
    return ThreadBorderRouter(
        name=_str(raw.get("name")),
        model=_str(raw.get("model_name")),
        vendor=_str(raw.get("vendor_name")),
        mac=_str(raw.get("mac")),
        ip=_str(raw.get("ip")),
        thread_version=_str(raw.get("thread_version")),
        network_name=_str(raw.get("network_name")),
        extended_address=_str(raw.get("extended_address")),
        reporter_mac=_str(raw.get("reporter_mac")),
        fresh=raw.get("fresh") if isinstance(raw.get("fresh"), bool) else None,
        first_seen=_iso(raw.get("first_seen_at")),
        last_seen=_iso(raw.get("last_seen_at")),
    )


def matter_fabric_from_controller(raw: Any) -> MatterFabric:
    raw = raw if isinstance(raw, dict) else {}
    return MatterFabric(
        label=_str(raw.get("label")),
        vendor_id=_int(raw.get("vendor_id")),
        vendor_name=_str(raw.get("vendor_name")),
    )


def thread_network_from_controller(raw: Any) -> ThreadNetwork:
    raw = raw if isinstance(raw, dict) else {}
    routers = raw.get("border_routers") if isinstance(raw.get("border_routers"), list) else []
    fabrics = raw.get("fabrics") if isinstance(raw.get("fabrics"), list) else []
    return ThreadNetwork(
        name=_str(raw.get("name")),
        extended_pan_id=_str(raw.get("extended_pan_id")),
        channel=_int(raw.get("channel")),
        device_count=_int(raw.get("devices")),
        controller=_str(raw.get("controller")),
        border_routers=[thread_border_router_from_controller(router) for router in routers if isinstance(router, dict)],
        fabrics=[matter_fabric_from_controller(fabric) for fabric in fabrics if isinstance(fabric, dict)],
        last_seen=_iso(raw.get("last_seen_at")),
    )


def matter_node_from_controller(raw: Any) -> MatterNode:
    raw = raw if isinstance(raw, dict) else {}
    error_code = raw.get("error_code")
    return MatterNode(
        node_id=_int(raw.get("node_id")),
        name=_str(raw.get("display_name")) or _str(raw.get("name")) or _str(raw.get("device_name")),
        device_name=_str(raw.get("device_name")),
        status=_str(raw.get("status")),
        controller=_str(raw.get("controller")),
        channel=_int(raw.get("channel")),
        thread_client_id=_str(raw.get("client_id")),
        has_identify=raw.get("has_identify") if isinstance(raw.get("has_identify"), bool) else None,
        error_code=str(error_code) if isinstance(error_code, (str, int)) and not isinstance(error_code, bool) else None,
        created_at=_iso(raw.get("created_at")),
        finished_at=_iso(raw.get("finished_at")),
    )
