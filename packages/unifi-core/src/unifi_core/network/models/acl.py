"""Shared field model for MAC ACL rules.

Single source of truth for list/get output and create/update input,
imported by both the MCP tool layer (``apps/network``) and the API
server (``apps/api``). Translation helpers convert between this
model's flat field names and the controller API's nested
traffic_source/traffic_destination structure.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class AclRule(BaseModel):
    """Canonical ACL rule model.

    Field metadata ``json_schema_extra={"mutable": False}`` marks fields
    that appear in list/get output but are not accepted by create/update.
    """

    # Read-only (output only)
    id: Optional[str] = Field(
        default=None,
        description="Unique rule ID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    source_type: Optional[str] = Field(
        default=None,
        description="Source matching type (always CLIENT_MAC)",
        json_schema_extra={"mutable": False},
    )
    destination_type: Optional[str] = Field(
        default=None,
        description="Destination matching type (always CLIENT_MAC)",
        json_schema_extra={"mutable": False},
    )

    # Mutable (accepted by create and update)
    name: str = Field(description="Descriptive rule name")
    acl_index: int = Field(description="Position in the rule chain (lower = evaluated first)")
    action: Literal["ALLOW", "BLOCK"] = Field(description="Rule action")
    enabled: bool = Field(default=True, description="Whether the rule is active")
    network_id: str = Field(description="Network/VLAN ID this rule applies to")
    source_macs: List[str] = Field(
        default_factory=list,
        description="Source MAC addresses (empty list = any source)",
    )
    destination_macs: List[str] = Field(
        default_factory=list,
        description="Destination MAC addresses (empty list = any destination)",
    )


MUTABLE_FIELDS = frozenset(
    name for name, info in AclRule.model_fields.items() if (info.json_schema_extra or {}).get("mutable") is not False
)

READ_ONLY_FIELDS = frozenset(
    name for name, info in AclRule.model_fields.items() if (info.json_schema_extra or {}).get("mutable") is False
)


def from_controller(raw: Dict[str, Any]) -> AclRule:
    """Build an AclRule from a controller API response dict.

    The controller returns nested traffic_source/traffic_destination
    objects; this flattens them to the model's canonical field names.
    """
    source = raw.get("traffic_source", {})
    destination = raw.get("traffic_destination", {})

    return AclRule(
        id=raw.get("_id"),
        name=raw.get("name", ""),
        acl_index=raw.get("acl_index", 0),
        action=raw.get("action", "BLOCK"),
        enabled=raw.get("enabled", True),
        network_id=raw.get("mac_acl_network_id", ""),
        source_type=source.get("type"),
        source_macs=source.get("specific_mac_addresses", []),
        destination_type=destination.get("type"),
        destination_macs=destination.get("specific_mac_addresses", []),
    )


def to_controller_create(rule: AclRule) -> Dict[str, Any]:
    """Build a controller API create payload from an AclRule."""
    return {
        "name": rule.name,
        "acl_index": rule.acl_index,
        "action": rule.action,
        "enabled": rule.enabled,
        "mac_acl_network_id": rule.network_id,
        "specific_enforcers": [],
        "traffic_source": {
            "ips_or_subnets": [],
            "network_ids": [],
            "ports": [],
            "specific_mac_addresses": rule.source_macs,
            "type": "CLIENT_MAC",
        },
        "traffic_destination": {
            "ips_or_subnets": [],
            "network_ids": [],
            "ports": [],
            "specific_mac_addresses": rule.destination_macs,
            "type": "CLIENT_MAC",
        },
        "type": "MAC",
    }


def validate_update_fields(fields: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Type-check a partial update dict against the AclRule field annotations.

    Field names are assumed to have been validated separately against
    MUTABLE_FIELDS. Returns (is_valid, error_message).
    """
    for field_name, value in fields.items():
        field_info = AclRule.model_fields.get(field_name)
        if field_info is None:
            continue
        try:
            TypeAdapter(field_info.annotation).validate_python(value, strict=True)
        except ValidationError as e:
            err = e.errors()[0]
            return False, f"Invalid value for '{field_name}': {err['msg']}"
    return True, None


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a partial update dict from model field names to controller shape.

    Only includes fields the caller provided.
    """
    result: Dict[str, Any] = {}

    if "source_macs" in fields:
        result["traffic_source"] = {
            "ips_or_subnets": [],
            "network_ids": [],
            "ports": [],
            "specific_mac_addresses": fields["source_macs"],
            "type": "CLIENT_MAC",
        }

    if "destination_macs" in fields:
        result["traffic_destination"] = {
            "ips_or_subnets": [],
            "network_ids": [],
            "ports": [],
            "specific_mac_addresses": fields["destination_macs"],
            "type": "CLIENT_MAC",
        }

    for model_key, controller_key in UPDATE_FIELD_MAP.items():
        if model_key in fields:
            result[controller_key] = fields[model_key]

    return result


UPDATE_FIELD_MAP: Dict[str, str] = {
    "name": "name",
    "acl_index": "acl_index",
    "action": "action",
    "enabled": "enabled",
    "network_id": "mac_acl_network_id",
}

MAC_TRANSLATED_FIELDS = frozenset({"source_macs", "destination_macs"})
