"""Shared field models for Network firewall policies, groups, and zones.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.firewall``.

- ``FirewallRule``  — CRUD for V2 zone-based firewall policies.
  Mutable fields per FIREWALL_POLICY_V2_CREATE_SCHEMA.
- ``FirewallGroup`` — create/delete for firewall address/port groups.
  Mutable fields: name, group_type, members.
- ``FirewallZone``  — zone shape with a mutable display name.
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

from pydantic import BaseModel, Field, ValidationError

from unifi_core.mac import canonical_mac, looks_like_mac, normalize_mac
from unifi_core.merge import deep_merge

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

_LEGACY_V1_FIREWALL_FIELDS = frozenset({"ruleset", "rule_index", "src_address", "dst_address", "src_port", "dst_port"})
_LEGACY_V1_ACTIONS = frozenset({"accept", "drop", "reject"})
_LEGACY_MIGRATION_ERROR = (
    "Legacy V1 firewall fields are no longer supported. "
    "Use V2 zone-based fields: action (ALLOW/BLOCK/REJECT), source "
    "(zone_id + matching_target), destination (zone_id + matching_target). "
    "See unifi_list_firewall_policies for examples of valid V2 shape."
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

FIREWALLGROUP_TYPES: frozenset[str] = frozenset({"address-group", "ipv6-address-group", "port-group"})
FIREWALLGROUP_UPDATE_FIELDS: frozenset[str] = frozenset({"name", "members"})


# ---------------------------------------------------------------------------
# FirewallZone pydantic model
# ---------------------------------------------------------------------------


class FirewallZone(BaseModel):
    """Canonical firewall zone model (mutable name only)."""

    id: Optional[str] = Field(
        default=None,
        description="V2 controller firewall-zone ObjectID (not an Integration API UUID)",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="Zone display name",
    )
    networks: Optional[List[Any]] = Field(
        default=None,
        description="Network IDs assigned to this zone (managed via network firewall_zone_id)",
        json_schema_extra={"mutable": False},
    )
    default_policy: Optional[str] = Field(
        default=None,
        description="Default action for traffic in this zone",
        json_schema_extra={"mutable": False},
    )


FIREWALLZONE_MUTABLE_FIELDS: frozenset[str] = frozenset({"name"})

FIREWALLZONE_READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name for name in FirewallZone.model_fields.keys() if name not in FIREWALLZONE_MUTABLE_FIELDS
)


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


def validate_policy_port_targeting(fields: Dict[str, Any]) -> None:
    """Reject malformed V2 create-policy ports before preview or controller I/O.

    Endpoints remain opaque controller dictionaries. Validate the confirmed
    SPECIFIC port contract without changing other targeting modes or values.
    """
    for direction in ("source", "destination"):
        endpoint = fields.get(direction)
        if not isinstance(endpoint, dict):
            continue
        if "ports" in endpoint:
            raise ValueError(
                "%s.ports is not a valid field; the controller expects %s.port as a single "
                "string (e.g. '445'), not a plural 'ports' array." % (direction, direction)
            )
        port = endpoint.get("port")
        if endpoint.get("port_matching_type") == "SPECIFIC" and not (isinstance(port, str) and port.strip()):
            raise ValueError("%s.port must be a non-empty string when port_matching_type is 'SPECIFIC'." % direction)


# ---------------------------------------------------------------------------
# Selector activation
# ---------------------------------------------------------------------------
# The controller stores a targeting selector only under the enum value that
# activates it; under any other value it accepts the field and silently ignores
# it. (selector key, activating enum key, activating value).

SELECTOR_ACTIVATORS: tuple[tuple[str, str, str], ...] = (
    ("client_macs", "matching_target", "CLIENT"),
    ("port", "port_matching_type", "SPECIFIC"),
    ("port_group_id", "port_matching_type", "OBJECT"),
)

# The only endpoint keys retire_stale_selectors may set to None, and therefore the
# only keys a None inside an endpoint is allowed to remove. Any other None is the
# caller's own and must reach the controller, which rejects it loudly.
RETIRABLE_SELECTORS: frozenset[str] = frozenset(selector for selector, _, _ in SELECTOR_ACTIVATORS)

# The endpoint keys that make a caller responsible for a selector's error. An error
# the stored policy already had is not an update's fault, unless the update wrote one
# of these keys - then the result is the caller's whatever it was before.
_SELECTOR_OWNER_KEYS: Dict[str, frozenset[str]] = {
    "matching_target": frozenset({"matching_target", "matching_target_type", "ips", "ip_group_id", "network_ids"}),
    "client_macs": frozenset({"client_macs", "matching_target"}),
    "port": frozenset({"port", "ports", "port_matching_type"}),
    "port_group_id": frozenset({"port_group_id", "port_matching_type"}),
    "match_opposite_ports": frozenset({"match_opposite_ports", "port_matching_type"}),
}

# The enum values this project has observed. A value outside its set is a controller
# target this project has not seen (App, Web, Region, ...): validation passes it
# through, and the list view keeps showing whatever the controller stored beside it
# rather than hiding a selector it may well be enforcing.
_KNOWN_ACTIVATOR_VALUES: Dict[str, frozenset[str]] = {
    "matching_target": frozenset({"ANY", "IP", "NETWORK", "CLIENT"}),
    "port_matching_type": frozenset({"ANY", "SPECIFIC", "OBJECT"}),
}


def activator_is_known(activator_key: str, value: Any) -> bool:
    """Whether an endpoint's enum value is one this project recognises."""
    return isinstance(value, str) and value.strip().upper() in _KNOWN_ACTIVATOR_VALUES.get(activator_key, frozenset())


def _activator_matches(value: Any, activator_value: str) -> bool:
    """Whether an endpoint's enum value activates its selector.

    Case- and space-insensitive: the MCP tool normalizes endpoint enums before
    validating, the API create translator does not, and a check that only knew
    the upper-case spelling gave the two surfaces opposite verdicts on the same
    policy.
    """
    return isinstance(value, str) and value.strip().upper() == activator_value


def _client_macs_error(direction: str, value: Any) -> str | None:
    """Reject a client_macs value, naming the position rather than the address.

    The message reaches tool logs and the API audit row, and a MAC address is
    one of the values this project never writes to either.
    """
    if not isinstance(value, list) or not value:
        return "%s.client_macs must be a non-empty array of MAC addresses when matching_target is 'CLIENT'." % direction
    for index, mac in enumerate(value):
        if not looks_like_mac(mac):
            return "%s.client_macs[%d] is not a MAC address; expected the AA:BB:CC:DD:EE:FF form." % (direction, index)
    return None


def _port_group_error(direction: str, value: Any) -> str | None:
    if not value:
        return "%s.port_group_id is required when port_matching_type is 'OBJECT'." % direction
    return None


# ``port`` under SPECIFIC is deliberately absent: its shape is
# :func:`validate_policy_port_targeting`'s contract, and this table only decides
# which selector belongs under which enum.
_SELECTOR_VALIDATORS = {
    "client_macs": _client_macs_error,
    "port_group_id": _port_group_error,
}


def zone_target_error(direction: str, ep: Any) -> str | None:
    """The completeness rule for one endpoint's ``matching_target``.

    IP and NETWORK each need a ``matching_target_type`` and the selector that goes
    with it; the controller stores an incomplete one and matches nothing, so a BLOCK
    policy silently stops blocking. Unknown targets pass through, like everywhere
    else in this module. A non-dict endpoint is :func:`validate_policy_selectors`'
    to report, so it is ignored here rather than reported twice.
    """
    if not isinstance(ep, dict):
        return None
    target = ep.get("matching_target")
    if target in ("IP", "NETWORK") and not ep.get("matching_target_type"):
        expected = "'SPECIFIC' or 'OBJECT'" if target == "IP" else "'OBJECT'"
        return "%s.matching_target_type is required when matching_target is '%s'. Use %s." % (
            direction,
            target,
            expected,
        )
    if target == "IP":
        target_type = ep.get("matching_target_type")
        if target_type == "OBJECT" and not ep.get("ip_group_id"):
            return "%s.ip_group_id is required when matching_target is 'IP' with matching_target_type 'OBJECT'." % (
                direction
            )
        if target_type != "OBJECT" and not ep.get("ips"):
            return "%s.ips array is required when matching_target is 'IP'." % direction
    if target == "NETWORK" and not ep.get("network_ids"):
        return "%s.network_ids array is required when matching_target is 'NETWORK'." % direction
    return None


def validate_zone_targeting(fields: Dict[str, Any]) -> str | None:
    """The first ``matching_target`` completeness error across both endpoints.

    Lived in the Network tool, where only ``unifi_create_firewall_policy`` called it,
    so an update and an API create could both write a target with nothing to match.
    Same messages and same order; the tool keeps its own name as a delegate.
    """
    for direction in ("source", "destination"):
        if error := zone_target_error(direction, fields.get(direction)):
            return error
    return None


def _selector_activator_errors(
    direction: str, ep: Dict[str, Any], *, require_both_present: bool = False
) -> List[tuple[str, str]]:
    """``(selector key, message)`` for every selector-vs-activating-enum problem.

    With ``require_both_present`` the check is limited to pairs the dict itself
    carries, which is what a partial update can be judged on without the stored
    policy.
    """
    activated: List[tuple[str, str]] = []
    leftover: List[tuple[str, str]] = []
    for selector, activator_key, activator_value in SELECTOR_ACTIVATORS:
        if require_both_present and (activator_key not in ep or selector not in ep):
            continue
        value = ep.get(selector)
        if _activator_matches(ep.get(activator_key), activator_value):
            validator = _SELECTOR_VALIDATORS.get(selector)
            error = validator(direction, value) if validator else None
            if error:
                activated.append((selector, error))
        elif value:
            # Directional on purpose. "port_matching_type must be 'OBJECT'" told a caller
            # who had just chosen SPECIFIC to undo that choice, when the thing to remove
            # was the port_group_id left behind. The enum's value is quoted only when it
            # is one this project knows, so no caller string reaches a log or audit row.
            current = ep.get(activator_key)
            shown = (
                "'%s'" % str(current).strip().upper()
                if activator_is_known(activator_key, current)
                else ("unset" if current is None else "an unrecognised value")
            )
            leftover.append(
                (
                    selector,
                    "%s.%s is ignored while %s.%s is %s. Remove it, or set %s.%s to '%s'."
                    % (direction, selector, direction, activator_key, shown, direction, activator_key, activator_value),
                )
            )
    if _activator_matches(ep.get("port_matching_type"), "ANY") and ep.get("match_opposite_ports"):
        leftover.append(
            (
                "match_opposite_ports",
                "%s.match_opposite_ports must be false when port_matching_type is 'ANY'." % direction,
            )
        )
    # What the chosen enum is missing comes first. Told "port_matching_type must be
    # 'SPECIFIC'" when they asked for OBJECT, a caller undoes the change they meant.
    return activated + leftover


def _endpoint_selector_errors(direction: str, ep: Any) -> List[tuple[str, str]]:
    """Selector problems on one source/destination value, in check order."""
    if ep is None:
        return []
    if not isinstance(ep, dict):
        return [("", "%s must be an object with zone_id and matching_target." % direction)]
    return _selector_activator_errors(direction, ep)


def validate_policy_selectors(fields: Dict[str, Any]) -> None:
    """Reject targeting selectors the controller would store and then ignore.

    Complements :func:`validate_policy_port_targeting` (the SPECIFIC ``port``
    shape) and the Network tool's zone/IP/NETWORK requirements: this function
    owns CLIENT targeting, the ``OBJECT`` port-group mode, and the rule that a
    selector only travels with the enum value that activates it. Unknown
    ``matching_target`` / ``port_matching_type`` values pass through so newer
    controller targets (App, Web, Region, ...) keep working.
    """
    for direction in ("source", "destination"):
        errors = _endpoint_selector_errors(direction, fields.get(direction))
        if errors:
            raise ValueError(errors[0][1])


def retire_stale_selectors(stored: Any, update: Any) -> Any:
    """Mark selectors a partial endpoint update deactivates for removal.

    A partial update that moves ``port_matching_type`` or ``matching_target``
    away from the value that activates a stored selector (``port``,
    ``port_group_id``, ``client_macs``) would otherwise deep-merge into a
    document carrying a selector the controller ignores. The returned copy of
    ``update`` sets each such selector to ``None``; the manager drops ``None``
    keys inside an endpoint before the PUT. Selectors the update sets itself
    are left alone.
    """
    if not isinstance(stored, dict) or not isinstance(update, dict):
        return update
    retired = dict(update)
    if (
        _activator_matches(update.get("port_matching_type"), "ANY")
        and "match_opposite_ports" not in update
        and stored.get("match_opposite_ports")
    ):
        retired["match_opposite_ports"] = False
    for selector, activator_key, activator_value in SELECTOR_ACTIVATORS:
        if activator_key not in update or selector in update:
            continue
        if not _activator_matches(update[activator_key], activator_value) and stored.get(selector) is not None:
            retired[selector] = None
    return retired


def _merged_endpoint_errors(direction: str, ep: Any) -> List[tuple[str, str]]:
    """``(selector key, message)`` for every targeting error this layer can see."""
    errors = _endpoint_selector_errors(direction, ep)
    if isinstance(ep, dict):
        if zone_error := zone_target_error(direction, ep):
            errors.append(("matching_target", zone_error))
        try:
            validate_policy_port_targeting({direction: ep})
        except ValueError as exc:
            errors.append(("port", str(exc)))
    return errors


def policy_update_targeting_error(current: Dict[str, Any], updates: Dict[str, Any]) -> str | None:
    """Return the first targeting error a partial update would introduce.

    The manager deep-merges ``source``/``destination`` with the stored policy,
    so each updated side is validated as merged. Sides the update does not
    touch are left alone, and errors the stored side already has (state this
    project did not author) are not held against an update that leaves them
    in place.
    """
    for side in ("source", "destination"):
        if side not in updates:
            continue
        stored = current.get(side)
        stored = stored if isinstance(stored, dict) else {}
        update = updates[side]
        merged = deep_merge(stored, update) if isinstance(update, dict) else update
        touched = set(update) if isinstance(update, dict) else set()
        preexisting = {key for key, _ in _merged_endpoint_errors(side, stored)}
        for key, message in _merged_endpoint_errors(side, merged):
            # Suppression is per selector, not per message: two updates to the same
            # bad selector produce the same words, and comparing the words would let
            # a caller write a new invalid value into an already-invalid selector.
            if key in preexisting and not (touched & _SELECTOR_OWNER_KEYS.get(key, frozenset({key}))):
                continue
            return message
    return None


def _selector_contradiction_error(direction: str, ep: Any) -> str | None:
    """Reject a selector paired with a non-activating enum inside one update dict.

    This needs no stored state, so it runs at the normalization boundary and
    protects previews on surfaces that cannot read the controller first.
    """
    if not isinstance(ep, dict):
        return None
    errors = _selector_activator_errors(direction, ep, require_both_present=True)
    return errors[0][1] if errors else None


def prepare_policy_update(current: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """Finish a normalized partial update against the stored policy document.

    This is the shared MCP/API step that needs controller state: it retires the
    selectors an activation change deactivates (:func:`retire_stale_selectors`)
    and validates each updated side as the controller will store it
    (:func:`policy_update_targeting_error`). Raises ``ValueError`` on the first
    targeting error; the manager calls it before building the PUT body and the
    MCP wrapper calls it for the preview.
    """
    # Upper-case the endpoint enums first: activation is compared case-insensitively
    # but validate_policy_port_targeting compares against the controller's spelling,
    # so a lower-case "specific" would look active to one check and inert to the other
    # and write a SPECIFIC endpoint with no port. create_firewall_policy normalizes for
    # the same reason.
    prepared = normalize_policy_endpoint_enums(updates)
    for side in ("source", "destination"):
        if side in prepared:
            prepared[side] = retire_stale_selectors(current.get(side), prepared[side])
    if error := policy_update_targeting_error(current, prepared):
        raise ValueError(error)
    return prepared


def legacy_policy_error(fields: Dict[str, Any]) -> str | None:
    """Return the actionable V1-to-V2 migration error when legacy input is detected."""
    if _LEGACY_V1_FIREWALL_FIELDS & set(fields):
        return _LEGACY_MIGRATION_ERROR
    action = fields.get("action")
    if isinstance(action, str) and action in _LEGACY_V1_ACTIONS:
        return _LEGACY_MIGRATION_ERROR
    return None


_ENDPOINT_ENUM_KEYS = ("matching_target", "matching_target_type", "port_matching_type")


def _normalize_endpoint_enums(endpoint: Any) -> Any:
    """Upper-case the enum-valued keys inside a source/destination endpoint dict."""
    if not isinstance(endpoint, dict):
        return endpoint
    return {
        k: (v.strip().upper() if k in _ENDPOINT_ENUM_KEYS and isinstance(v, str) else v) for k, v in endpoint.items()
    }


def normalize_policy_endpoint_enums(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Upper-case the source/destination enum values and nothing else.

    The narrow half of :func:`normalize_policy_enums`, for the create paths that
    must not also validate and rewrite the top-level fields. The controller stores
    these enums upper-case; a validator comparing against the upper-case spelling
    on one surface and not the other is how two surfaces reach opposite verdicts
    on the same policy.
    """
    normalized = dict(fields)
    for side in ("source", "destination"):
        if side in normalized:
            normalized[side] = _normalize_endpoint_enums(normalized[side])
    return normalized


def normalize_policy_enums(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Upper-case the controller's V2 firewall enum values."""
    normalized = dict(fields)
    action = normalized.get("action")
    if isinstance(action, str):
        upper_action = action.upper()
        if upper_action not in {"ALLOW", "BLOCK", "REJECT"}:
            # No echo of the submitted value: this message reaches the API audit row,
            # which scrubs secret-keyed values only.
            raise ValueError("Invalid action; must be one of ALLOW, BLOCK, REJECT.")
        normalized["action"] = upper_action
    for key in ("ip_version", "connection_state_type"):
        if isinstance(normalized.get(key), str):
            normalized[key] = normalized[key].upper()
    states = normalized.get("connection_states")
    if isinstance(states, list):
        normalized["connection_states"] = [state.upper() if isinstance(state, str) else state for state in states]
    return normalize_policy_endpoint_enums(normalized)


def _normalize_endpoint_macs(endpoint: Any) -> Any:
    """Lowercase the ``client_macs`` inside a source/destination endpoint dict.

    ``source`` and ``destination`` are opaque ``Dict[str, Any]`` on the model,
    so nothing else inspects what they carry - but on a CLIENT matching_target
    they hold a MAC list that must round-trip against what the controller
    reports.
    """
    if not isinstance(endpoint, dict) or "client_macs" not in endpoint:
        return endpoint
    macs = endpoint["client_macs"]
    if not isinstance(macs, list):
        return endpoint
    # The controller reports colon-separated pairs and validation accepts the dashed
    # and bare-hex spellings too, so send the canonical form rather than whichever
    # one the caller happened to type.
    return {**endpoint, "client_macs": [canonical_mac(mac) or normalize_mac(mac) or mac for mac in macs]}


def normalize_policy_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a public V2 firewall-policy partial update.

    This is the shared mutation boundary for MCP and API callers. It rejects
    ``index`` (ordering is a separate tool family), rejects retired V1 fields,
    normalizes the controller's upper-case enums, drops unknown/read-only
    fields through :func:`to_controller_update`, and rejects a selector paired
    with a non-activating enum in the same update. Checks that need the stored
    policy run in :func:`prepare_policy_update`.
    """
    if "index" in fields:
        # The V2 policy endpoint accepts index and silently ignores it, so the
        # caller would get a partly applied update. Ordering is its own tool family.
        raise ValueError(
            "index cannot be changed with unifi_update_firewall_policy; the controller "
            "ignores it on this endpoint. Use unifi_reorder_firewall_policies to change policy order."
        )
    if error := legacy_policy_error(fields):
        raise ValueError(error)
    normalized = normalize_policy_enums(fields)

    payload = to_controller_update(normalized)
    for side in ("source", "destination"):
        if side in payload:
            if error := _selector_contradiction_error(side, payload[side]):
                raise ValueError(error)
            payload[side] = _normalize_endpoint_macs(payload[side])
    if not payload:
        raise ValueError("Update data is effectively empty or invalid.")
    return payload


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


def validate_group_create(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a public firewall-group create payload and return controller fields."""
    if not isinstance(fields, dict):
        raise ValueError("Firewall group data must be an object.")

    unknown = sorted(set(fields) - FIREWALLGROUP_MUTABLE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown or read-only firewall group field(s): {', '.join(unknown)}")

    missing = [field for field in ("name", "group_type", "members") if field not in fields]
    if missing:
        raise ValueError(f"Missing required firewall group field(s): {', '.join(missing)}")

    try:
        model = FirewallGroup(**fields)
    except ValidationError as error:
        raise ValueError(f"Invalid firewall group data: {error.errors()[0]['msg']}") from None

    if not model.name or not model.name.strip():
        raise ValueError("Firewall group 'name' must not be empty.")
    if model.group_type not in FIREWALLGROUP_TYPES:
        allowed = ", ".join(sorted(FIREWALLGROUP_TYPES))
        raise ValueError(f"Firewall group 'group_type' must be one of: {allowed}.")
    return to_group_create(model)


def validate_group_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a public partial firewall-group update and return controller fields."""
    if not isinstance(fields, dict):
        raise ValueError("Firewall group update_data must be an object.")
    if "group_type" in fields:
        raise ValueError("Firewall group 'group_type' cannot be changed after creation.")

    unknown = sorted(set(fields) - FIREWALLGROUP_UPDATE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown or read-only firewall group update field(s): {', '.join(unknown)}")
    if not fields:
        raise ValueError("No firewall group fields provided for update.")

    try:
        model = FirewallGroup(**fields)
    except ValidationError as error:
        raise ValueError(f"Invalid firewall group update data: {error.errors()[0]['msg']}") from None

    if "name" in fields and (not model.name or not model.name.strip()):
        raise ValueError("Firewall group 'name' must not be empty.")

    payload: Dict[str, Any] = {}
    if "name" in fields:
        payload["name"] = model.name
    if "members" in fields:
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


def to_zone_create(model: FirewallZone) -> Dict[str, Any]:
    """Produce an integration-API create payload for a firewall zone.

    The integration API rejects a missing/``null`` ``networkIds``, so a new
    zone is always created with an empty membership; networks join via the
    network-level ``firewall_zone_id`` field instead.
    """
    return {
        "name": model.name,
        "networkIds": [],
    }


def to_zone_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to the mutable firewall-zone keys only.

    ``name`` is the only writable field; ``None`` values and unrecognised keys
    are dropped.
    """
    return {k: v for k, v in fields.items() if k in FIREWALLZONE_MUTABLE_FIELDS and v is not None}


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
