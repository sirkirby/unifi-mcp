"""Projection mechanics shared by the Drive Strawberry types."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from typing import Any, ClassVar

from strawberry.types.base import StrawberryOptional
from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.redaction import redact_sensitive_fields

from unifi_api.graphql.types.sitemanager._base import plain
from unifi_api.services.drive import ID_FAMILY

DESCRIPTION = f"UniFi Drive read, through the NAS console session. {ID_FAMILY}"


class Projection:
    """Builds a type from a core model or dict: declared fields only, redacted by policy, JSON-safe."""

    _nested: ClassVar[dict[str, tuple[type, bool]]] = {}
    _identity: ClassVar[str | None] = None
    _columns: ClassVar[list[str]] = []

    @classmethod
    def render_hint(cls, kind: str) -> dict[str, Any]:
        hint: dict[str, Any] = {"kind": kind, "display_columns": list(cls._columns)}
        if cls._identity is not None:
            hint["primary_key"] = cls._identity
        return hint

    @classmethod
    def from_manager_output(cls, obj: Any, *, redact_sensitive: bool = True) -> Any:
        data = redact_sensitive_fields(plain(obj), redact_sensitive=redact_sensitive)
        if not isinstance(data, dict):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable result")
        try:
            json.dumps(data, allow_nan=False)
        except (ValueError, TypeError):
            raise UniFiMalformedResponseError("UniFi Drive returned unreadable projection data") from None
        values = {field.name: data.get(field.name) for field in fields(cls)}
        if any(values[field.name] is None and not isinstance(field.type, StrawberryOptional) for field in fields(cls)):
            # A required field the NAS's reply did not carry: the reply is not a readable result.
            raise UniFiMalformedResponseError("UniFi Drive returned a result without a required field")
        for key, (nested, many) in cls._nested.items():
            value = values[key]
            if value is None:
                continue
            values[key] = (
                [nested.from_manager_output(item, redact_sensitive=False) for item in value]
                if many
                else nested.from_manager_output(value, redact_sensitive=False)
            )
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
