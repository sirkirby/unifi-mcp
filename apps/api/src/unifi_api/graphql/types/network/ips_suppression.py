"""Public IPS signature suppression and detection exclusion projection."""

from __future__ import annotations

from dataclasses import asdict

import strawberry
from unifi_core.network.models.ips_suppression import IpsSuppressions as CoreIpsSuppressions
from unifi_core.redaction import redact_sensitive_fields

from unifi_api.graphql.scalars import BigInt


@strawberry.type(description="An address excluded from all IPS detection.")
class IpsExclusion:
    scope: str | None = strawberry.field(description="source, destination, or both; null if unknown.")
    direction: str | None = strawberry.field(description="Raw controller direction.")
    mode: str | None = strawberry.field(description="Raw controller target kind, such as ip or subnet.")
    target: str | None = strawberry.field(description="Excluded address, subnet, or network.")


@strawberry.type(description="One suppressed IPS signature for one target, or for all traffic.")
class IpsSuppression:
    signature_id: BigInt = strawberry.field(description="Signature ID.")
    gid: BigInt | None = strawberry.field(description="Signature generator ID.")
    signature: str | None = strawberry.field(description="Signature name.")
    category: str | None = strawberry.field(description="Signature category.")
    suppression_type: str | None = strawberry.field(description="Raw controller type, such as all or track.")
    scope: str | None = strawberry.field(description="global, source, destination, or both; null if unknown.")
    direction: str | None = strawberry.field(description="Raw controller direction.")
    mode: str | None = strawberry.field(description="Raw controller target kind, such as ip or subnet.")
    target: str | None = strawberry.field(description="Suppressed address, subnet, or network.")


@strawberry.type(description="IPS signature suppressions and detection exclusions for a site.")
class IpsSuppressions:
    suppressions: list[IpsSuppression] = strawberry.field(description="One entry per signature and target.")
    exclusions: list[IpsExclusion] = strawberry.field(description="Addresses excluded from all detection.")

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: CoreIpsSuppressions, *, redact_sensitive: bool = True) -> "IpsSuppressions":
        data = redact_sensitive_fields(obj.model_dump(), redact_sensitive=redact_sensitive)
        return cls(
            suppressions=[IpsSuppression(**entry) for entry in data["suppressions"]],
            exclusions=[IpsExclusion(**entry) for entry in data["exclusions"]],
        )

    def to_dict(self) -> dict:
        return asdict(self)
