"""Strawberry types for network/dynamic_dns (Dynamic DNS provider entries).

One type per read serializer, mirroring the pydantic domain model in
``unifi_core.network.models.dynamic_dns``:

- ``DynamicDns`` — list_dynamic_dns + get_dynamic_dns_entry_details

Field names map 1:1 to the controller keys. The provider secret
``x_password`` is redacted at this surface via ``redact_value`` (per the
response redaction policy); ``from_manager_output`` carries every other
field through unchanged.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.redaction import redact_value


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A Dynamic DNS provider entry configured on the controller.")
class DynamicDns:
    id: strawberry.ID | None
    site_id: str | None
    host_name: str | None
    service: str | None
    server: str | None
    login: str | None
    x_password: str | None
    interface: str | None
    custom_service: str | None
    options: list[str] | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["host_name", "service", "interface", "login"],
            "sort_default": "host_name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "DynamicDns":
        options = _get(obj, "options")
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            site_id=_get(obj, "site_id"),
            host_name=_get(obj, "host_name"),
            service=_get(obj, "service"),
            server=_get(obj, "server"),
            login=_get(obj, "login"),
            x_password=redact_value("x_password", _get(obj, "x_password"), redact_sensitive=redact_sensitive),
            interface=_get(obj, "interface"),
            custom_service=_get(obj, "custom_service"),
            options=list(options) if isinstance(options, list) else None,
        )

    def to_dict(self) -> dict:
        return asdict(self)
