"""Shared field models for the Integration API ACL rule ordering family.

Mirrors the resources documented at
``/v1/sites/{siteId}/acl-rules`` and ``/v1/sites/{siteId}/acl-rules/ordering``
(UniFi Network API).

- ``IntegrationAclRule`` — one rule as the Integration API lists it (read-only)

The ordering payload itself is the ``orderedAclRuleIds`` UUID array carried on
``AclManager.get_acl_rule_ordering``/``reorder_acl_rules``; the list entries'
``id`` values are that array's ID source.

Integration ACL IDs are a different family from the V2 controller API's
``_id`` ObjectIDs; the two must not be interchanged. ``metadata`` and any
future fields are passed through unmodified so a newer controller's extras
still round-trip.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

MUTABLE_FIELDS = frozenset()  # Read-only: no create/update tools in this domain.
READ_ONLY_FIELDS = frozenset({"id"})


class IntegrationAclRule(BaseModel):
    """One MAC ACL rule as the Integration API lists it (read-only)."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    id: str = Field(
        description="Integration API UUID; the value the ordering endpoints use",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(default=None, description="Rule name as the controller reports it")
    index: Optional[int] = Field(default=None, description="Rule position in the Integration API's chain", ge=0)
    action: Optional[str] = Field(default=None, description="ALLOW or BLOCK, as the controller reports it")
    enabled: Optional[bool] = Field(default=None, description="Whether the rule is enabled")
    type: Optional[str] = Field(default=None, description="Rule type as the controller reports it (e.g. MAC)")
    network_id_filter: Optional[Any] = Field(
        default=None,
        description="networkIdFilter exactly as the controller returned it (shape not documented)",
    )
    raw: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Fields the controller returned beyond the ones modelled above "
            "(metadata and future additions), passed through unmodified"
        ),
    )


def integration_acl_rule_from_controller(raw: Dict[str, Any]) -> IntegrationAclRule:
    """Normalise one controller rule dict into an IntegrationAclRule."""
    if not isinstance(raw, dict):
        raise ValueError("Controller returned an invalid ACL rule list response")
    rule_id = raw.get("id")
    if rule_id is None:
        raise ValueError("Controller returned an ACL rule without an id")
    modelled = {"id", "name", "index", "action", "enabled", "type", "networkIdFilter"}
    raw_rest = {key: value for key, value in raw.items() if key not in modelled}
    return IntegrationAclRule(
        id=str(rule_id),
        name=raw.get("name"),
        index=raw.get("index"),
        action=raw.get("action"),
        enabled=raw.get("enabled"),
        type=raw.get("type"),
        network_id_filter=raw.get("networkIdFilter"),
        raw=raw_rest or None,
    )
