"""Projection mechanics shared by explicit Site Manager Strawberry types."""

import json
from dataclasses import asdict, fields, is_dataclass
from typing import ClassVar

from pydantic import BaseModel
from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.redaction import redact_sensitive_fields

VISIBILITY = "A READ key sees every resource the cloud account can see."
ID_FAMILY = "These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools."
DESCRIPTION = f"{VISIBILITY} {ID_FAMILY}"


def plain(value):
    if isinstance(value, BaseModel):
        return value.model_dump()
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


class Projection:
    _nested: ClassVar[dict] = {}
    _identity: ClassVar[str | None] = None
    _columns: ClassVar[list[str]] = []

    @classmethod
    def render_hint(cls, kind):
        hint = {"kind": kind, "display_columns": list(cls._columns)}
        if cls._identity is not None:
            hint["primary_key"] = cls._identity
        return hint

    @classmethod
    def from_manager_output(cls, obj, *, redact_sensitive=True):
        data = redact_sensitive_fields(plain(obj), redact_sensitive=redact_sensitive)
        try:
            json.dumps(data, allow_nan=False)
        except (ValueError, TypeError):
            raise UniFiMalformedResponseError("Site Manager returned unreadable projection data") from None
        values = {field.name: data[field.name] for field in fields(cls)}
        for key, (nested, many) in cls._nested.items():
            value = values[key]
            values[key] = (
                [nested.from_manager_output(item, redact_sensitive=False) for item in value]
                if many
                else nested.from_manager_output(value, redact_sensitive=False)
            )
        return cls(**values)

    def to_dict(self):
        return asdict(self)
