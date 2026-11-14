"""Explicit Site Manager sdwan read shapes."""

import strawberry
from strawberry.scalars import JSON

from unifi_api.graphql.types.sitemanager._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class SiteManagerSdwanConfigSummary(Projection):
    id: str | None = strawberry.field(description="SD-WAN configuration id")
    name: str | None = strawberry.field(description="Configuration name")
    type: str | None = strawberry.field(description="Topology type")
    _identity = "id"
    _columns = ["name"]


@strawberry.type(description=DESCRIPTION)
class SiteManagerSdwanConfig(Projection):
    id: str | None = strawberry.field(description="SD-WAN configuration id")
    name: str | None = strawberry.field(description="Configuration name")
    type: str | None = strawberry.field(description="Topology type")
    variant: str | None = strawberry.field(description="Topology variant")
    settings: JSON = strawberry.field(description="Configuration settings")
    hubs: list[JSON] = strawberry.field(description="Hub members")
    spokes: list[JSON] = strawberry.field(description="Spoke members")
    _identity = "id"
    _columns = ["name"]


@strawberry.type(description=DESCRIPTION)
class SiteManagerSdwanConfigStatus(Projection):
    id: str | None = strawberry.field(description="SD-WAN configuration id")
    fingerprint: str | None = strawberry.field(description="Fingerprint of the generated configuration")
    generate_status: str | None = strawberry.field(description="Status of configuration generation")
    updated_at: JSON | None = strawberry.field(description="When the status was last updated")
    last_generated_at: JSON | None = strawberry.field(description="When the configuration was generated")
    errors: list[JSON] = strawberry.field(description="Configuration-level errors")
    warnings: list[JSON] = strawberry.field(description="Configuration-level warnings")
    hubs: list[JSON] = strawberry.field(description="Per-hub status")
    spokes: list[JSON] = strawberry.field(description="Per-spoke status")
    _identity = "id"
    _columns = ["generate_status", "updated_at"]


@strawberry.type(description=DESCRIPTION)
class SiteManagerSdwanConfigList(Projection):
    items: list[SiteManagerSdwanConfigSummary]
    next_cursor: str | None
    _nested = {"items": (SiteManagerSdwanConfigSummary, True)}
