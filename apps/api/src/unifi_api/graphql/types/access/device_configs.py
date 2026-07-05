"""Strawberry type for access/device configs.

Projects a single per-device ``configs[]`` entry (the settings the Access web
UI edits, e.g. the reader voice greeting) for ``access_get_device_configs``.

Redaction: the secret rides in ``value`` while its name lives in ``key`` — so
field-name redaction can't see it. ``from_manager_output`` redacts ``value``
when the entry is credential-tagged or its key trips the shared secret
vocabulary (:func:`is_sensitive_config`), and accepts ``redact_sensitive`` so
the action endpoint's policy gate is honored.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.access.models.device_configs import is_sensitive_config
from unifi_core.redaction import REDACTED


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A single per-device config/settings entry (key/value with category tag).")
class AccessDeviceConfig:
    """Mirrors the ``unifi_core`` ``DeviceConfigEntry`` model."""

    device_id: strawberry.ID | None
    key: str | None
    value: str | None
    tag: str | None
    update_time: str | None
    create_time: str | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "key",
            "display_columns": ["key", "value", "tag"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> "AccessDeviceConfig":
        key = _get(obj, "key")
        tag = _get(obj, "tag")
        value = _get(obj, "value")
        if redact_sensitive and value is not None and is_sensitive_config(key, tag):
            value = REDACTED
        return cls(
            device_id=_get(obj, "device_id"),
            key=key,
            value=value,
            tag=tag,
            update_time=_get(obj, "update_time"),
            create_time=_get(obj, "create_time"),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}
