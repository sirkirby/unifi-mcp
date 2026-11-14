"""Typed Teleport VPN settings.

Teleport is UniFi's zero-configuration remote-access VPN. Its site setting is a
singleton record (``/get/setting/teleport``) holding an ``enabled`` flag and the
client address range as ``subnet_cidr`` in gateway-address form, for example
``192.168.2.1/24``. The UniFi UI shows neither field for editing: the gateway
picks the first unused ``192.168.x.0/24`` when Teleport is first enabled, which
can collide with a network a remote client is visiting.

Only ``subnet_cidr`` is writable here. Turning Teleport off and on again is left
to the UI: per community reports it discards every Teleport client invitation
and lets the gateway pick a new range.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from pydantic import BaseModel, Field

MUTABLE_FIELDS = frozenset({"subnet_cidr"})

# Teleport hands out RFC 1918 addresses; anything else would route public space.
_PRIVATE_RANGES = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)
# /24 is the size the controller picks itself and the only one verified on
# hardware. The bounds keep the range a usable client pool.
MIN_PREFIX = 16
MAX_PREFIX = 29


class TeleportSettings(BaseModel):
    """Public read view of the Teleport site setting."""

    enabled: bool | None = Field(
        default=None,
        description="Whether Teleport is enabled (read-only here; toggle it in the UniFi UI)",
        json_schema_extra={"mutable": False},
    )
    subnet_cidr: str | None = Field(
        default=None,
        description=(
            "Teleport client address range in gateway-address form (e.g. '192.168.2.1/24'); "
            "null when the controller has not assigned one"
        ),
    )
    id: str | None = Field(default=None, description="Setting record id", json_schema_extra={"mutable": False})
    site_id: str | None = Field(default=None, description="Site id", json_schema_extra={"mutable": False})


TELEPORTSETTINGS_MUTABLE_FIELDS: frozenset[str] = MUTABLE_FIELDS
TELEPORTSETTINGS_READ_ONLY_FIELDS: frozenset[str] = frozenset(TeleportSettings.model_fields) - MUTABLE_FIELDS


def teleport_from_controller(raw: Any) -> TeleportSettings:
    """Project the known fields of a Teleport record (list or dict).

    The model is the allowlist: unrelated keys a future controller adds to the
    record never reach the result.
    """
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, dict):
        return TeleportSettings()
    enabled = raw.get("enabled")
    subnet = raw.get("subnet_cidr")
    return TeleportSettings(
        enabled=enabled if isinstance(enabled, bool) else None,
        subnet_cidr=subnet if isinstance(subnet, str) and subnet else None,
        id=raw.get("_id", raw.get("id")),
        site_id=raw.get("site_id", raw.get("site")),
    )


def validate_teleport_subnet(value: Any) -> str:
    """Return ``value`` normalised if it is a usable Teleport range, else raise ``ValueError``.

    Accepts gateway-address form only (``10.201.0.1/24``): the controller
    stores the range that way, and a bare network address
    (``10.201.0.0/24``) would make the gateway claim the network address.
    Error messages name the rule broken, never echo the value.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("subnet_cidr must be a non-empty string such as '10.201.0.1/24'")
    if "/" not in value:
        raise ValueError("subnet_cidr must include a prefix length, such as '10.201.0.1/24'")
    try:
        interface = ipaddress.IPv4Interface(value.strip())
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
        raise ValueError("subnet_cidr must be an IPv4 address with a prefix length, such as '10.201.0.1/24'") from None
    network = interface.network
    if not MIN_PREFIX <= network.prefixlen <= MAX_PREFIX:
        raise ValueError(f"subnet_cidr prefix length must be between /{MIN_PREFIX} and /{MAX_PREFIX}")
    if not any(network.subnet_of(private) for private in _PRIVATE_RANGES):
        raise ValueError("subnet_cidr must lie inside a private (RFC 1918) range")
    if interface.ip in (network.network_address, network.broadcast_address):
        raise ValueError(
            "subnet_cidr must name the gateway address inside the range (e.g. '10.201.0.1/24'), "
            "not the network or broadcast address"
        )
    return str(interface)


def teleport_to_controller_update(fields: dict[str, Any]) -> dict[str, Any]:
    """Validate an exact partial update; return only supplied mutable keys.

    Errors name fields only, never the rejected values.
    """
    if not isinstance(fields, dict) or not fields:
        raise ValueError("No Teleport fields provided")
    unknown = set(fields) - MUTABLE_FIELDS
    if unknown:
        raise ValueError(f"Invalid Teleport field: {', '.join(sorted(unknown))}")
    return {"subnet_cidr": validate_teleport_subnet(fields["subnet_cidr"])}


def teleport_subnet_conflicts(subnet_cidr: str, networks: list[dict[str, Any]]) -> list[str]:
    """Names of configured networks whose ``ip_subnet`` overlaps ``subnet_cidr``.

    Covers every networkconf record that carries an IPv4 ``ip_subnet``: LANs,
    VLANs and the other VPN servers' client ranges. Unparseable subnets are
    skipped, not treated as conflicts.
    """
    wanted = ipaddress.IPv4Interface(subnet_cidr).network
    conflicts: list[str] = []
    for record in networks:
        if not isinstance(record, dict):
            continue
        subnet = record.get("ip_subnet")
        if not isinstance(subnet, str) or not subnet:
            continue
        try:
            existing = ipaddress.IPv4Interface(subnet).network
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
            continue
        if wanted.overlaps(existing):
            name = record.get("name")
            conflicts.append(name if isinstance(name, str) and name else str(record.get("_id", "unnamed network")))
    return sorted(conflicts)
