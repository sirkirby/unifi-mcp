"""Shared field model for Network Dynamic DNS entries (read + create/update).

Mirrors the Strawberry type in
``unifi_api.graphql.types.network.dynamic_dns``.

- ``DynamicDns`` — list_dynamic_dns + get_dynamic_dns +
  create_dynamic_dns + update_dynamic_dns

The controller stores these under the V1 ``/rest/dynamicdns`` collection.
Field names map 1:1 to the controller keys (``host_name``, ``service``,
``server``, ``login``, ``x_password``, ``interface``, ``custom_service``,
``options``); ``_id`` and ``site_id`` are controller-assigned read-only keys.

The provider credential ``x_password`` is carried raw here — redaction happens
at the egress boundary (see ``unifi_core.redaction``), never in the model.

Factory helpers:
- ``from_controller``      — normalise the raw controller dict → DynamicDns
- ``to_controller_create`` — translate a DynamicDns → create payload
- ``to_controller_update`` — filter a partial dict to mutable keys only

``MUTABLE_FIELDS`` drives the cross-layer symmetry test.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class DynamicDns(BaseModel):
    """Canonical Dynamic DNS entry model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Dynamic DNS entry ID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    site_id: Optional[str] = Field(
        default=None,
        description="Controller site ID this entry belongs to",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    host_name: Optional[str] = Field(
        default=None,
        description="Hostname to keep updated (e.g. 'home.example.com')",
    )
    service: Optional[str] = Field(
        default=None,
        description="DDNS provider: 'dyndns', 'noip', 'namecheap', 'cloudflare', 'custom', etc.",
    )
    server: Optional[str] = Field(
        default=None,
        description="Update server host (used by the 'custom' service)",
    )
    login: Optional[str] = Field(
        default=None,
        description="Provider account username / login",
    )
    x_password: Optional[str] = Field(
        default=None,
        description="Provider password or API token (secret — redacted at egress)",
    )
    interface: Optional[str] = Field(
        default=None,
        description="WAN interface to track: 'wan' or 'wan2'",
    )
    custom_service: Optional[str] = Field(
        default=None,
        description="Custom provider identifier (used by the 'custom' service)",
    )
    options: Optional[List[str]] = Field(
        default=None,
        description="Extra provider options",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in DynamicDns.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in DynamicDns.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> DynamicDns:
    """Build a DynamicDns from a controller API response dict."""
    options_raw = _get(raw, "options")
    options = list(options_raw) if isinstance(options_raw, list) else None
    return DynamicDns(
        id=_get(raw, "_id") or _get(raw, "id"),
        site_id=_get(raw, "site_id"),
        host_name=_get(raw, "host_name"),
        service=_get(raw, "service"),
        server=_get(raw, "server"),
        login=_get(raw, "login"),
        x_password=_get(raw, "x_password"),
        interface=_get(raw, "interface"),
        custom_service=_get(raw, "custom_service"),
        options=options,
    )


def to_controller_create(model: DynamicDns) -> Dict[str, Any]:
    """Produce a controller create payload from a DynamicDns."""
    payload: Dict[str, Any] = {}
    if model.host_name is not None:
        payload["host_name"] = model.host_name
    if model.service is not None:
        payload["service"] = model.service
    if model.server is not None:
        payload["server"] = model.server
    if model.login is not None:
        payload["login"] = model.login
    if model.x_password is not None:
        payload["x_password"] = model.x_password
    if model.interface is not None:
        payload["interface"] = model.interface
    if model.custom_service is not None:
        payload["custom_service"] = model.custom_service
    if model.options is not None:
        payload["options"] = model.options
    return payload


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped. ``None`` values are
    dropped so an omitted field never clears controller state.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}
