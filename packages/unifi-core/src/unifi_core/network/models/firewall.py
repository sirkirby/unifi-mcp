"""Shared field models for Network firewall policies, groups, and zones.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.firewall``.

- ``FirewallRule``  — CRUD for V2 zone-based firewall policies.
  Mutable fields per FIREWALL_POLICY_V2_CREATE_SCHEMA.
- ``FirewallGroup`` — create/delete for firewall address/port groups.
  Mutable fields: name, group_type, members.
- ``FirewallZone``  — read-only zone shape (no mutable fields).
- ``LegacyFirewallRule`` — read-only pre-zone-based rule shape. The legacy
  engine uses different field names, lowercase actions, and flat
  source/destination fields, so it cannot share ``FirewallRule``.

Factory helpers:
- ``from_controller``              — raw dict → FirewallRule
- ``to_controller_create``         — FirewallRule → create payload
- ``to_controller_update``         — partial dict → mutable-only update
- ``firewall_group_from_controller`` — raw dict → FirewallGroup
- ``to_group_create``              — FirewallGroup → create payload
- ``firewall_zone_from_controller`` — raw dict → FirewallZone
- ``legacy_firewall_rule_from_controller`` — raw dict → LegacyFirewallRule

``MUTABLE_FIELDS`` is for FirewallRule and drives the cross-layer
symmetry test. Per-class aliases are provided for FirewallGroup and
FirewallZone.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# FirewallRule pydantic model
# ---------------------------------------------------------------------------


class FirewallRule(BaseModel):
    """Canonical V2 zone-based firewall policy model."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Firewall policy UUID",
        json_schema_extra={"mutable": False},
    )
    predefined: Optional[bool] = Field(
        default=None,
        description="Whether this is a controller-defined (non-editable) policy",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    name: Optional[str] = Field(
        default=None,
        description="Policy name",
    )
    action: Optional[str] = Field(
        default=None,
        description="Policy action: ALLOW, BLOCK, REJECT",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the policy is active",
    )
    index: Optional[int] = Field(
        default=None,
        description="Rule priority/order (lower = evaluated first)",
    )
    protocol: Optional[str] = Field(
        default=None,
        description="Protocol to match (e.g. 'all', 'tcp', 'udp', 'icmp')",
    )
    ip_version: Optional[str] = Field(
        default=None,
        description="IP version: BOTH, IPV4, IPV6",
    )
    connection_state_type: Optional[str] = Field(
        default=None,
        description="Connection state matching mode: ALL, RESPOND_ONLY, CUSTOM",
    )
    connection_states: List[str] = Field(
        default_factory=list,
        description="Connection states to match when connection_state_type=CUSTOM",
    )
    create_allow_respond: Optional[bool] = Field(
        default=None,
        description="Auto-create return traffic rule for ALLOW policies",
    )
    match_ip_sec: Optional[bool] = Field(
        default=None,
        description="Match IPSec traffic",
    )
    match_opposite_protocol: Optional[bool] = Field(
        default=None,
        description="Match opposite protocol",
    )
    icmp_typename: Optional[str] = Field(
        default=None,
        description="ICMP type name",
    )
    icmp_v6_typename: Optional[str] = Field(
        default=None,
        description="ICMPv6 type name",
    )
    schedule: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Schedule object (e.g. {'mode': 'ALWAYS'})",
    )
    source: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Source targeting (zone_id + matching_target)",
    )
    destination: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Destination targeting (zone_id + matching_target)",
    )
    logging: Optional[bool] = Field(
        default=None,
        description="Enable logging for matched traffic",
    )


# ---------------------------------------------------------------------------
# FirewallRule field sets
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in FirewallRule.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in FirewallRule.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# FirewallGroup pydantic model
# ---------------------------------------------------------------------------


class FirewallGroup(BaseModel):
    """Canonical firewall address/port group model."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="Firewall group UUID",
        json_schema_extra={"mutable": False},
    )

    # --- mutable ---
    name: Optional[str] = Field(
        default=None,
        description="Group name",
    )
    group_type: Optional[str] = Field(
        default=None,
        description="Group type: address-group, ipv6-address-group, or port-group",
    )
    members: List[str] = Field(
        default_factory=list,
        description="Group members: IPs/CIDRs or port numbers/ranges",
    )


FIREWALLGROUP_MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in FirewallGroup.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

FIREWALLGROUP_READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in FirewallGroup.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)


# ---------------------------------------------------------------------------
# FirewallZone pydantic model (read-only)
# ---------------------------------------------------------------------------


class FirewallZone(BaseModel):
    """Canonical firewall zone model (read-only)."""

    id: Optional[str] = Field(
        default=None,
        description="Zone UUID",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="Zone display name",
        json_schema_extra={"mutable": False},
    )
    networks: Optional[List[Any]] = Field(
        default=None,
        description="Network IDs assigned to this zone",
        json_schema_extra={"mutable": False},
    )
    default_policy: Optional[str] = Field(
        default=None,
        description="Default action for traffic in this zone",
        json_schema_extra={"mutable": False},
    )


FIREWALLZONE_MUTABLE_FIELDS: frozenset[str] = frozenset()

FIREWALLZONE_READ_ONLY_FIELDS: frozenset[str] = frozenset(FirewallZone.model_fields.keys())


# ---------------------------------------------------------------------------
# LegacyFirewallRule pydantic model (read-only, pre-zone-based engine)
# ---------------------------------------------------------------------------

#: Rulesets accepted by the legacy engine, including the IPv6 variants.
LEGACY_RULESETS: frozenset[str] = frozenset(
    {
        "WAN_IN",
        "WAN_OUT",
        "WAN_LOCAL",
        "LAN_IN",
        "LAN_OUT",
        "LAN_LOCAL",
        "GUEST_IN",
        "GUEST_OUT",
        "GUEST_LOCAL",
        "WANv6_IN",
        "WANv6_OUT",
        "WANv6_LOCAL",
        "LANv6_IN",
        "LANv6_OUT",
        "LANv6_LOCAL",
        "GUESTv6_IN",
        "GUESTv6_OUT",
        "GUESTv6_LOCAL",
    }
)

#: Legacy actions are lowercase, unlike the V2 engine's ALLOW/BLOCK/REJECT.
LEGACY_ACTIONS: frozenset[str] = frozenset({"accept", "drop", "reject"})


class LegacyFirewallRule(BaseModel):
    """Canonical pre-zone-based (legacy) firewall rule model (read-only).

    Distinct from :class:`FirewallRule`, which models the V2 zone-based engine.
    The two engines use different field names, different action casing, and
    different source/destination shapes, so they cannot share a model.
    """

    id: Optional[str] = Field(
        default=None,
        description="Legacy firewall rule ID",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="Rule name",
        json_schema_extra={"mutable": False},
    )
    ruleset: Optional[str] = Field(
        default=None,
        description=(
            "Ruleset the rule belongs to, e.g. WAN_IN, LAN_OUT, GUEST_LOCAL, or an IPv6 variant such as LANv6_IN"
        ),
        json_schema_extra={"mutable": False},
    )
    rule_index: Optional[int] = Field(
        default=None,
        description="Evaluation order within the ruleset (lower runs first)",
        json_schema_extra={"mutable": False},
    )
    action: Optional[str] = Field(
        default=None,
        description="Action for matched traffic: accept, drop, or reject (lowercase)",
        json_schema_extra={"mutable": False},
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Whether the rule is active",
        json_schema_extra={"mutable": False},
    )
    protocol: Optional[str] = Field(
        default=None,
        description="IPv4 protocol match, e.g. all, tcp, udp, tcp_udp, icmp",
        json_schema_extra={"mutable": False},
    )
    protocol_v6: Optional[str] = Field(
        default=None,
        description="IPv6 protocol match",
        json_schema_extra={"mutable": False},
    )
    protocol_match_excepted: Optional[bool] = Field(
        default=None,
        description="Invert the protocol match",
        json_schema_extra={"mutable": False},
    )
    src_address: Optional[str] = Field(
        default=None,
        description="Source address or CIDR",
        json_schema_extra={"mutable": False},
    )
    src_address_ipv6: Optional[str] = Field(
        default=None,
        description="Source IPv6 address or CIDR",
        json_schema_extra={"mutable": False},
    )
    src_port: Optional[str] = Field(
        default=None,
        description="Source port or range",
        json_schema_extra={"mutable": False},
    )
    src_mac_address: Optional[str] = Field(
        default=None,
        description="Source MAC address match",
        json_schema_extra={"mutable": False},
    )
    src_firewallgroup_ids: List[str] = Field(
        default_factory=list,
        description="Source firewall group IDs (address or port groups)",
        json_schema_extra={"mutable": False},
    )
    src_networkconf_id: Optional[str] = Field(
        default=None,
        description="Source network (VLAN) ID",
        json_schema_extra={"mutable": False},
    )
    src_networkconf_type: Optional[str] = Field(
        default=None,
        description="How the source network is matched: ADDRv4 or NETv4",
        json_schema_extra={"mutable": False},
    )
    dst_address: Optional[str] = Field(
        default=None,
        description="Destination address or CIDR",
        json_schema_extra={"mutable": False},
    )
    dst_address_ipv6: Optional[str] = Field(
        default=None,
        description="Destination IPv6 address or CIDR",
        json_schema_extra={"mutable": False},
    )
    dst_port: Optional[str] = Field(
        default=None,
        description="Destination port or range",
        json_schema_extra={"mutable": False},
    )
    dst_firewallgroup_ids: List[str] = Field(
        default_factory=list,
        description="Destination firewall group IDs (address or port groups)",
        json_schema_extra={"mutable": False},
    )
    dst_networkconf_id: Optional[str] = Field(
        default=None,
        description="Destination network (VLAN) ID",
        json_schema_extra={"mutable": False},
    )
    dst_networkconf_type: Optional[str] = Field(
        default=None,
        description="How the destination network is matched: ADDRv4 or NETv4",
        json_schema_extra={"mutable": False},
    )
    state_new: Optional[bool] = Field(
        default=None,
        description="Match connections in the NEW state",
        json_schema_extra={"mutable": False},
    )
    state_established: Optional[bool] = Field(
        default=None,
        description="Match connections in the ESTABLISHED state",
        json_schema_extra={"mutable": False},
    )
    state_related: Optional[bool] = Field(
        default=None,
        description="Match connections in the RELATED state",
        json_schema_extra={"mutable": False},
    )
    state_invalid: Optional[bool] = Field(
        default=None,
        description="Match connections in the INVALID state",
        json_schema_extra={"mutable": False},
    )
    icmp_typename: Optional[str] = Field(
        default=None,
        description="ICMP type match",
        json_schema_extra={"mutable": False},
    )
    icmpv6_typename: Optional[str] = Field(
        default=None,
        description="ICMPv6 type match",
        json_schema_extra={"mutable": False},
    )
    ipsec: Optional[str] = Field(
        default=None,
        description="IPsec match: match-ipsec or match-none",
        json_schema_extra={"mutable": False},
    )
    logging: Optional[bool] = Field(
        default=None,
        description="Whether matched traffic is logged",
        json_schema_extra={"mutable": False},
    )
    setting_preference: Optional[str] = Field(
        default=None,
        description="Whether the rule is auto-managed or manually configured",
        json_schema_extra={"mutable": False},
    )
    no_edit: Optional[bool] = Field(
        default=None,
        description="Controller-defined rule that cannot be edited",
        json_schema_extra={"mutable": False},
    )
    no_delete: Optional[bool] = Field(
        default=None,
        description="Controller-defined rule that cannot be deleted",
        json_schema_extra={"mutable": False},
    )


LEGACYFIREWALLRULE_MUTABLE_FIELDS: frozenset[str] = frozenset()

LEGACYFIREWALLRULE_READ_ONLY_FIELDS: frozenset[str] = frozenset(LegacyFirewallRule.model_fields.keys())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# FirewallRule factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> FirewallRule:
    """Build a FirewallRule from a controller API response dict or object."""
    raw_dict = getattr(raw, "raw", raw) if not isinstance(raw, dict) else raw
    if not isinstance(raw_dict, dict):
        raw_dict = {}

    enabled_raw = raw_dict.get("enabled", None)
    enabled = enabled_raw if isinstance(enabled_raw, bool) else None

    predefined_raw = raw_dict.get("predefined", None)
    predefined = predefined_raw if isinstance(predefined_raw, bool) else None

    connection_states = raw_dict.get("connection_states") or []
    if not isinstance(connection_states, list):
        connection_states = []

    return FirewallRule(
        id=raw_dict.get("_id") or raw_dict.get("id"),
        name=raw_dict.get("name"),
        action=raw_dict.get("action"),
        enabled=enabled,
        predefined=predefined,
        index=raw_dict.get("index") or raw_dict.get("rule_index"),
        protocol=raw_dict.get("protocol"),
        ip_version=raw_dict.get("ip_version"),
        connection_state_type=raw_dict.get("connection_state_type"),
        connection_states=list(connection_states),
        create_allow_respond=raw_dict.get("create_allow_respond"),
        match_ip_sec=raw_dict.get("match_ip_sec"),
        match_opposite_protocol=raw_dict.get("match_opposite_protocol"),
        icmp_typename=raw_dict.get("icmp_typename"),
        icmp_v6_typename=raw_dict.get("icmp_v6_typename"),
        schedule=raw_dict.get("schedule"),
        source=raw_dict.get("source"),
        destination=raw_dict.get("destination"),
        logging=raw_dict.get("logging"),
    )


def to_controller_create(model: FirewallRule) -> Dict[str, Any]:
    """Produce a controller create payload from a FirewallRule."""
    payload: Dict[str, Any] = {}
    for field_name in MUTABLE_FIELDS:
        val = getattr(model, field_name, None)
        if val is not None:
            payload[field_name] = val
    return payload


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}


# ---------------------------------------------------------------------------
# FirewallGroup factory helpers
# ---------------------------------------------------------------------------


def firewall_group_from_controller(raw: Any) -> FirewallGroup:
    """Build a FirewallGroup from a controller API response dict."""
    members = _get(raw, "group_members") or _get(raw, "members") or []
    if not isinstance(members, list):
        members = []
    return FirewallGroup(
        id=_get(raw, "_id") or _get(raw, "id"),
        name=_get(raw, "name"),
        group_type=_get(raw, "group_type"),
        members=list(members),
    )


def to_group_create(model: FirewallGroup) -> Dict[str, Any]:
    """Produce a controller create payload for a firewall group."""
    payload: Dict[str, Any] = {}
    if model.name is not None:
        payload["name"] = model.name
    if model.group_type is not None:
        payload["group_type"] = model.group_type
    payload["group_members"] = model.members
    return payload


# ---------------------------------------------------------------------------
# FirewallZone factory helper
# ---------------------------------------------------------------------------


def firewall_zone_from_controller(raw: Any) -> FirewallZone:
    """Build a FirewallZone from a controller API response dict."""
    networks = _get(raw, "networks") or _get(raw, "network_ids") or []
    if not isinstance(networks, list):
        networks = []
    return FirewallZone(
        id=_get(raw, "_id") or _get(raw, "id"),
        name=_get(raw, "name"),
        networks=list(networks),
        default_policy=_get(raw, "default_policy") or _get(raw, "default_action"),
    )


def _str_list(value: Any) -> List[str]:
    """Coerce a controller value to a list of strings, dropping anything else."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _opt_bool(value: Any) -> Optional[bool]:
    """Preserve ``False`` while treating a missing or non-bool value as unknown."""
    return value if isinstance(value, bool) else None


def legacy_firewall_rule_from_controller(raw: Any) -> LegacyFirewallRule:
    """Build a LegacyFirewallRule from a ``/rest/firewallrule`` response entry."""
    rule_index = _get(raw, "rule_index")
    if not isinstance(rule_index, int) or isinstance(rule_index, bool):
        try:
            rule_index = int(rule_index)
        except (TypeError, ValueError):
            rule_index = None

    return LegacyFirewallRule(
        id=_get(raw, "_id") or _get(raw, "id"),
        name=_get(raw, "name"),
        ruleset=_get(raw, "ruleset"),
        rule_index=rule_index,
        action=_get(raw, "action"),
        enabled=_opt_bool(_get(raw, "enabled")),
        protocol=_get(raw, "protocol"),
        protocol_v6=_get(raw, "protocol_v6"),
        protocol_match_excepted=_opt_bool(_get(raw, "protocol_match_excepted")),
        src_address=_get(raw, "src_address"),
        src_address_ipv6=_get(raw, "src_address_ipv6"),
        src_port=_get(raw, "src_port"),
        src_mac_address=_get(raw, "src_mac_address"),
        src_firewallgroup_ids=_str_list(_get(raw, "src_firewallgroup_ids")),
        src_networkconf_id=_get(raw, "src_networkconf_id"),
        src_networkconf_type=_get(raw, "src_networkconf_type"),
        dst_address=_get(raw, "dst_address"),
        dst_address_ipv6=_get(raw, "dst_address_ipv6"),
        dst_port=_get(raw, "dst_port"),
        dst_firewallgroup_ids=_str_list(_get(raw, "dst_firewallgroup_ids")),
        dst_networkconf_id=_get(raw, "dst_networkconf_id"),
        dst_networkconf_type=_get(raw, "dst_networkconf_type"),
        state_new=_opt_bool(_get(raw, "state_new")),
        state_established=_opt_bool(_get(raw, "state_established")),
        state_related=_opt_bool(_get(raw, "state_related")),
        state_invalid=_opt_bool(_get(raw, "state_invalid")),
        icmp_typename=_get(raw, "icmp_typename"),
        icmpv6_typename=_get(raw, "icmpv6_typename"),
        ipsec=_get(raw, "ipsec"),
        logging=_opt_bool(_get(raw, "logging")),
        setting_preference=_get(raw, "setting_preference"),
        no_edit=_opt_bool(_get(raw, "attr_no_edit")),
        no_delete=_opt_bool(_get(raw, "attr_no_delete")),
    )
