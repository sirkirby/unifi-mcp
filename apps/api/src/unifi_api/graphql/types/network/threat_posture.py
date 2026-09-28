"""Typed, allowlisted Network CyberSecure threat posture read."""

from __future__ import annotations

from dataclasses import asdict

import strawberry
from unifi_core.network.models.threat_posture import ThreatPosture as CoreThreatPosture
from unifi_core.redaction import redact_sensitive_fields

from unifi_api.graphql.scalars import BigInt


@strawberry.type(description="Signature status from a legacy Network gateway device.")
class GatewaySignature:
    device_id: strawberry.ID | None = strawberry.field(
        description="Legacy Network device ID, not an Integration API UUID; null if unknown."
    )
    mac_address: str | None = strawberry.field(description="Gateway MAC address; null if unknown.")
    name: str | None = strawberry.field(description="Gateway display name; null if unknown.")
    rule_count: BigInt | None = strawberry.field(description="Signature rule count; null if unknown.")
    update_time: BigInt | None = strawberry.field(
        description="Signature update time in Unix milliseconds; null if unknown."
    )
    signature_type: str | None = strawberry.field(description="Controller signature type; null if unknown.")
    is_activating: bool | None = strawberry.field(description="Activation state; null if unknown.")


@strawberry.type(description="CyberSecure summary and gateway signature status for a selected period.")
class ThreatPosture:
    period: str = strawberry.field(description="HOUR, DAY, WEEK, or MONTH.")
    enterprise: bool | None = strawberry.field(description="Enterprise status; null if unknown.")
    has_subscription: bool | None = strawberry.field(description="Subscription status; null if unknown.")
    ips_enabled: bool | None = strawberry.field(description="IPS enabled state; null if unknown.")
    is_activating: bool | None = strawberry.field(description="Activation state; null if unknown.")
    scanned_bytes: BigInt | None = strawberry.field(description="Scanned bytes during the period; null if unknown.")
    signature_capacity: BigInt | None = strawberry.field(description="Signature capacity; null if unknown.")
    signatures: BigInt | None = strawberry.field(description="Signature count; null if unknown.")
    threats: BigInt | None = strawberry.field(description="Threat count during the period; null if unknown.")
    updated_timestamp: BigInt | None = strawberry.field(
        description="Summary update time in Unix milliseconds; null if unknown."
    )
    gateway_signatures: list[GatewaySignature] = strawberry.field(
        description="Allowlisted per-gateway signature status."
    )

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: CoreThreatPosture, *, redact_sensitive: bool = True) -> "ThreatPosture":
        data = redact_sensitive_fields(obj.model_dump(), redact_sensitive=redact_sensitive)
        return cls(
            period=data["period"],
            enterprise=data["enterprise"],
            has_subscription=data["has_subscription"],
            ips_enabled=data["ips_enabled"],
            is_activating=data["is_activating"],
            scanned_bytes=data["scanned_bytes"],
            signature_capacity=data["signature_capacity"],
            signatures=data["signatures"],
            threats=data["threats"],
            updated_timestamp=data["updated_timestamp"],
            gateway_signatures=[GatewaySignature(**record) for record in data["gateway_signatures"]],
        )

    def to_dict(self) -> dict:
        return asdict(self)
