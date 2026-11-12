"""Site Manager SD-WAN (Site Magic) configurations and their deployment status.

Hub, spoke and status entries are nested and loosely specified, so their
members are passed through as the API sent them rather than modelled field by
field.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.sitemanager.models._coerce import as_dict, as_list, text, timestamp


class SdwanConfigSummary(BaseModel):
    """One SD-WAN configuration in a listing."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, description="SD-WAN configuration id")
    name: str | None = Field(default=None, description="Configuration name")
    type: str | None = Field(default=None, description="Topology type")


class SdwanConfig(SdwanConfigSummary):
    """An SD-WAN configuration with its settings, hubs and spokes."""

    variant: str | None = Field(default=None, description="Topology variant")
    settings: dict[str, Any] = Field(default_factory=dict, description="Configuration settings")
    hubs: list[dict[str, Any]] = Field(default_factory=list, description="Hub members")
    spokes: list[dict[str, Any]] = Field(default_factory=list, description="Spoke members")


class SdwanConfigStatus(BaseModel):
    """Deployment status of an SD-WAN configuration."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, description="SD-WAN configuration id")
    fingerprint: str | None = Field(default=None, description="Fingerprint of the generated configuration")
    generate_status: str | None = Field(default=None, description="Status of configuration generation")
    updated_at: str | int | None = Field(default=None, description="When the status was last updated")
    last_generated_at: str | int | None = Field(default=None, description="When the configuration was generated")
    errors: list[Any] = Field(default_factory=list, description="Configuration-level errors")
    warnings: list[Any] = Field(default_factory=list, description="Configuration-level warnings")
    hubs: list[dict[str, Any]] = Field(default_factory=list, description="Per-hub status")
    spokes: list[dict[str, Any]] = Field(default_factory=list, description="Per-spoke status")


def _members(value: Any) -> list[dict[str, Any]]:
    return [member for member in as_list(value) if isinstance(member, dict)]


def sdwan_summary_from_api(raw: Any) -> SdwanConfigSummary:
    config = as_dict(raw)
    return SdwanConfigSummary(id=text(config.get("id")), name=text(config.get("name")), type=text(config.get("type")))


def sdwan_config_from_api(raw: Any) -> SdwanConfig:
    config = as_dict(raw)
    return SdwanConfig(
        id=text(config.get("id")),
        name=text(config.get("name")),
        type=text(config.get("type")),
        variant=text(config.get("variant")),
        settings=as_dict(config.get("settings")),
        hubs=_members(config.get("hubs")),
        spokes=_members(config.get("spokes")),
    )


def sdwan_status_from_api(raw: Any) -> SdwanConfigStatus:
    status = as_dict(raw)
    return SdwanConfigStatus(
        id=text(status.get("id")),
        fingerprint=text(status.get("fingerprint")),
        generate_status=text(status.get("generateStatus")),
        updated_at=timestamp(status.get("updatedAt")),
        last_generated_at=timestamp(status.get("lastGeneratedAt")),
        errors=as_list(status.get("errors")),
        warnings=as_list(status.get("warnings")),
        hubs=_members(status.get("hubs")),
        spokes=_members(status.get("spokes")),
    )
