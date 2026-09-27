"""Read-only, allowlisted Network threat posture projection."""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class GatewaySignature(BaseModel):
    """Signature status reported by one gateway; timestamps are milliseconds."""

    model_config = ConfigDict(extra="forbid")

    device_id: StrictStr | None = Field(
        default=None,
        description=(
            "Legacy Network device ID for this gateway; not a public Integration API device UUID. Null if unknown."
        ),
        json_schema_extra={"mutable": False},
    )
    mac_address: StrictStr | None = Field(
        default=None, description="Gateway MAC address; null if unknown.", json_schema_extra={"mutable": False}
    )
    name: StrictStr | None = Field(
        default=None, description="Gateway display name; null if unknown.", json_schema_extra={"mutable": False}
    )
    rule_count: StrictInt | None = Field(
        default=None,
        description="Installed signature rule count; null if unknown.",
        json_schema_extra={"mutable": False},
    )
    update_time: StrictInt | None = Field(
        default=None,
        description="Gateway signature update timestamp in Unix milliseconds; null if unknown.",
        json_schema_extra={"mutable": False},
    )
    signature_type: StrictStr | None = Field(
        default=None, description="Controller signature type; null if unknown.", json_schema_extra={"mutable": False}
    )
    is_activating: StrictBool | None = Field(
        default=None,
        description="Whether gateway signatures are activating; null if unknown, never inferred as false.",
        json_schema_extra={"mutable": False},
    )


class ThreatPosture(BaseModel):
    """CyberSecure summary and gateway signatures; timestamps use milliseconds."""

    model_config = ConfigDict(extra="forbid")

    period: StrictStr = Field(
        description="Summary period: HOUR, DAY, WEEK, or MONTH.", json_schema_extra={"mutable": False}
    )
    enterprise: StrictBool | None = Field(
        default=None, description="Enterprise status; null if unknown.", json_schema_extra={"mutable": False}
    )
    has_subscription: StrictBool | None = Field(
        default=None, description="Subscription status; null if unknown.", json_schema_extra={"mutable": False}
    )
    ips_enabled: StrictBool | None = Field(
        default=None, description="IPS enabled status; null if unknown.", json_schema_extra={"mutable": False}
    )
    is_activating: StrictBool | None = Field(
        default=None, description="Activation status; null if unknown.", json_schema_extra={"mutable": False}
    )
    scanned_bytes: StrictInt | None = Field(
        default=None,
        description="Bytes scanned during the period; null if unknown.",
        json_schema_extra={"mutable": False},
    )
    signature_capacity: StrictInt | None = Field(
        default=None, description="Signature capacity; null if unknown.", json_schema_extra={"mutable": False}
    )
    signatures: StrictInt | None = Field(
        default=None, description="Signature count; null if unknown.", json_schema_extra={"mutable": False}
    )
    threats: StrictInt | None = Field(
        default=None, description="Threat count for the period; null if unknown.", json_schema_extra={"mutable": False}
    )
    updated_timestamp: StrictInt | None = Field(
        default=None,
        description="Summary update timestamp in Unix milliseconds; null if unknown.",
        json_schema_extra={"mutable": False},
    )
    gateway_signatures: list[GatewaySignature] = Field(
        description="Allowlisted signature status for gateways in the Network device collection.",
        json_schema_extra={"mutable": False},
    )


MUTABLE_FIELDS: frozenset[str] = frozenset()
READ_ONLY_FIELDS: frozenset[str] = frozenset(ThreatPosture.model_fields)
GATEWAY_SIGNATURE_READ_ONLY_FIELDS: frozenset[str] = frozenset(GatewaySignature.model_fields)


_BOOL_FIELDS = ("enterprise", "has_subscription", "ips_enabled", "is_activating")
_INT_FIELDS = ("scanned_bytes", "signature_capacity", "signatures", "threats", "updated_timestamp")


def _typed(raw: dict[str, Any], key: str, expected: type) -> Any:
    value = raw.get(key)
    return value if type(value) is expected else None


def threat_posture_from_controller(period: str, summary: dict[str, Any], devices: Iterable[Any]) -> ThreatPosture:
    """Select verified fields only, including when response redaction is disabled."""
    gateways: list[GatewaySignature] = []
    for device in devices:
        raw = device if isinstance(device, dict) else getattr(device, "raw", None)
        if not isinstance(raw, dict):
            continue
        signature = raw.get("ids_ips_signature")
        if not isinstance(signature, dict):
            continue
        gateways.append(
            GatewaySignature(
                device_id=_typed(raw, "_id", str),
                mac_address=_typed(raw, "mac", str),
                name=_typed(raw, "name", str),
                rule_count=_typed(signature, "rule_count", int),
                update_time=_typed(signature, "update_time", int),
                signature_type=_typed(signature, "signature_type", str),
                is_activating=_typed(signature, "is_activating", bool),
            )
        )

    return ThreatPosture(
        period=period,
        gateway_signatures=gateways,
        **{key: _typed(summary, key, bool) for key in _BOOL_FIELDS},
        **{key: _typed(summary, key, int) for key in _INT_FIELDS},
    )
