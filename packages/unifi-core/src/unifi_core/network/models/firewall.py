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

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from unifi_core.mac import looks_like_mac, normalize_mac_list
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
    "Legacy V1 firewall fields are no longer supported (#210). "
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


def legacy_policy_error(fields: Dict[str, Any]) -> str | None:
    """Return the actionable V1-to-V2 migration error when legacy input is detected."""
    if _LEGACY_V1_FIREWALL_FIELDS & set(fields):
        return _LEGACY_MIGRATION_ERROR
    action = fields.get("action")
    if isinstance(action, str) and action in _LEGACY_V1_ACTIONS:
        return _LEGACY_MIGRATION_ERROR
    return None


_ENDPOINT_ENUM_KEYS = ("matching_target", "matching_target_type", "port_matching_type")
_PORT_TOKEN = re.compile(r"^(\d{1,5})(?:-(\d{1,5}))?$")


def _normalize_endpoint_enums(endpoint: Any) -> Any:
    """Upper-case the enum-valued keys inside a source/destination endpoint dict."""
    if not isinstance(endpoint, dict):
        return endpoint
    return {
        k: (v.strip().upper() if k in _ENDPOINT_ENUM_KEYS and isinstance(v, str) else v) for k, v in endpoint.items()
    }


def normalize_policy_enums(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Upper-case the controller's V2 firewall enum values."""
    normalized = dict(fields)
    action = normalized.get("action")
    if isinstance(action, str):
        upper_action = action.upper()
        if upper_action not in {"ALLOW", "BLOCK", "REJECT"}:
            raise ValueError(f"Invalid action '{action}'.")
        normalized["action"] = upper_action
    for key in ("ip_version", "connection_state_type"):
        if isinstance(normalized.get(key), str):
            normalized[key] = normalized[key].upper()
    states = normalized.get("connection_states")
    if isinstance(states, list):
        normalized["connection_states"] = [state.upper() if isinstance(state, str) else state for state in states]
    for side in ("source", "destination"):
        if side in normalized:
            normalized[side] = _normalize_endpoint_enums(normalized[side])
    return normalized


def _port_string_error(direction: str, value: Any) -> str | None:
    """Validate a V2 ``port`` string: comma-separated ports or ``low-high`` ranges, 1-65535."""
    if not isinstance(value, str) or not value:
        return "%s.port must be a non-empty string when port_matching_type is 'SPECIFIC'." % direction
    for token in value.split(","):
        match = _PORT_TOKEN.fullmatch(token)
        if not match:
            return (
                "%s.port %r must be a comma-separated list of ports or low-high ranges "
                "with no spaces, e.g. '53,853' or '1000-2000'." % (direction, value)
            )
        low = int(match.group(1))
        high = int(match.group(2)) if match.group(2) else low
        if not (1 <= low <= 65535 and 1 <= high <= 65535) or low > high:
            return "%s.port '%s' must use ports 1-65535 with ranges written low-high." % (direction, value)
    return None


def _client_macs_error(direction: str, value: Any) -> str | None:
    if not isinstance(value, list) or not value or any(not looks_like_mac(mac) for mac in value):
        return "%s.client_macs %r must be a non-empty array of MAC addresses when matching_target is 'CLIENT'." % (
            direction,
            value,
        )
    return None


def _port_group_error(direction: str, value: Any) -> str | None:
    if not value:
        return "%s.port_group_id is required when port_matching_type is 'OBJECT'." % direction
    return None


# (selector key, the enum key that activates it, the activating value). A selector present
# under any other enum value is ignored by the controller, so it is rejected on write and
# hidden in list summaries.
SELECTOR_ACTIVATORS: tuple[tuple[str, str, str], ...] = (
    ("client_macs", "matching_target", "CLIENT"),
    ("port", "port_matching_type", "SPECIFIC"),
    ("port_group_id", "port_matching_type", "OBJECT"),
)
_SELECTOR_VALIDATORS = {
    "client_macs": _client_macs_error,
    "port": _port_string_error,
    "port_group_id": _port_group_error,
}


def _endpoint_targeting_errors(direction: str, ep: Any) -> List[str]:
    """Every targeting problem on one source/destination endpoint, in check order."""
    if ep is None:
        return []
    if not isinstance(ep, dict):
        return ["%s must be an object with zone_id and matching_target." % direction]
    errors: List[str] = []
    target = ep.get("matching_target")
    if target in ("IP", "NETWORK") and not ep.get("matching_target_type"):
        expected = "'SPECIFIC' or 'OBJECT'" if target == "IP" else "'OBJECT'"
        errors.append(
            "%s.matching_target_type is required when matching_target is '%s'. Use %s." % (direction, target, expected)
        )
    if target == "IP":
        target_type = ep.get("matching_target_type")
        if target_type == "OBJECT" and not ep.get("ip_group_id"):
            errors.append(
                "%s.ip_group_id is required when matching_target is 'IP' with matching_target_type 'OBJECT'."
                % direction
            )
        if target_type != "OBJECT" and not ep.get("ips"):
            errors.append("%s.ips array is required when matching_target is 'IP'." % direction)
    if target == "NETWORK" and not ep.get("network_ids"):
        errors.append("%s.network_ids array is required when matching_target is 'NETWORK'." % direction)
    errors.extend(_selector_activator_errors(direction, ep))
    return errors


def _selector_activator_errors(direction: str, ep: Dict[str, Any], *, require_both_present: bool = False) -> List[str]:
    """Selector-vs-activating-enum problems on one endpoint dict.

    With ``require_both_present`` the check is limited to pairs the dict itself
    carries, which is what a partial update can be judged on without the
    stored policy.
    """
    errors: List[str] = []
    for selector, activator_key, activator_value in SELECTOR_ACTIVATORS:
        if require_both_present and (activator_key not in ep or selector not in ep):
            continue
        value = ep.get(selector)
        if ep.get(activator_key) == activator_value:
            error = _SELECTOR_VALIDATORS[selector](direction, value)
            if error:
                errors.append(error)
        elif value:
            # The controller stores and enforces a selector only under its activating enum;
            # anything else would be accepted and silently ignored.
            errors.append(
                "%s.%s must be '%s' when %s.%s is set."
                % (direction, activator_key, activator_value, direction, selector)
            )
    return errors


def validate_policy_targeting(fields: Dict[str, Any]) -> str | None:
    """Validate V2 zone-based source/destination targeting.

    Returns the first error message or ``None``. Enforces the requirements of
    the matching targets and port matching types this project has observed on
    live controllers (ANY / IP / NETWORK / CLIENT; ANY / SPECIFIC / OBJECT).
    Other values pass through untouched so newer controller targets (App,
    Web, Region, ...) keep working through update calls.
    """
    for direction in ("source", "destination"):
        errors = _endpoint_targeting_errors(direction, fields.get(direction))
        if errors:
            return errors[0]
    return None


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
    for selector, activator_key, activator_value in SELECTOR_ACTIVATORS:
        if activator_key not in update or selector in update:
            continue
        if update[activator_key] != activator_value and stored.get(selector) is not None:
            retired[selector] = None
    return retired


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
        preexisting = set(_endpoint_targeting_errors(side, stored))
        for error in _endpoint_targeting_errors(side, merged):
            if error not in preexisting:
                return error
    return None


def _selector_contradiction_error(direction: str, ep: Any) -> str | None:
    """Reject a selector paired with a non-activating enum inside one update dict.

    This needs no stored state, so it runs at the normalization boundary and
    protects previews on surfaces that cannot read the controller first.
    """
    if not isinstance(ep, dict):
        return None
    errors = _selector_activator_errors(direction, ep, require_both_present=True)
    return errors[0] if errors else None


def prepare_policy_update(current: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """Finish a normalized partial update against the stored policy document.

    This is the shared MCP/API step that needs controller state: it retires the
    selectors an activation change deactivates (:func:`retire_stale_selectors`)
    and validates each updated side as the controller will store it
    (:func:`policy_update_targeting_error`). Raises ``ValueError`` on the first
    targeting error; the manager calls it before building the PUT body and the
    MCP wrapper calls it for the preview.
    """
    prepared = dict(updates)
    for side in ("source", "destination"):
        if side in prepared:
            prepared[side] = retire_stale_selectors(current.get(side), prepared[side])
    if error := policy_update_targeting_error(current, prepared):
        raise ValueError(error)
    return prepared


def _normalize_endpoint_macs(endpoint: Any) -> Any:
    """Lowercase the ``client_macs`` inside a source/destination endpoint dict.

    ``source`` and ``destination`` are opaque ``Dict[str, Any]`` on the model,
    so nothing else inspects what they carry - but on a CLIENT matching_target
    they hold a MAC list that must round-trip against what the controller
    reports.
    """
    if not isinstance(endpoint, dict) or "client_macs" not in endpoint:
        return endpoint
    return {**endpoint, "client_macs": normalize_mac_list(endpoint["client_macs"])}


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
