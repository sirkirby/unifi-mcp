"""Strawberry types for network/firewall (rules + groups + zones).

Phase 6 PR2 Task 22 migration target. Three read shapes that used to live in
``unifi_api.serializers.network.firewall_rules``:

- ``FirewallRule``  — list_firewall_policies + get_firewall_policy_details
                      (also resource-keyed at ``network/firewall/rules`` and
                      ``network/firewall/rules/{id}``)
- ``FirewallGroup`` — list_firewall_groups + get_firewall_group_details
                      (V1 ``/rest/firewallgroup``; ``group_members`` is
                      re-exposed as ``members``)
- ``FirewallZone``  — list_firewall_zones (V2 zone-matrix; the manager strips
                      the policy-count matrix before this layer sees it)
- ``FirewallPolicyOrdering`` — get_firewall_policy_ordering
                               (Integration API zone-pair ordering object)

The mutation ack serializer (``FirewallMutationAckSerializer``) is preserved
in the original module since it covers create/update/delete/toggle for both
firewall policies and firewall groups.

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/firewall_rules.py. ``to_dict()``
exposes the same dict contract the REST routes return today.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry
from unifi_core.network.models.firewall import legacy_firewall_rule_from_controller


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A firewall policy rule.")
class FirewallRule:
    id: strawberry.ID | None
    name: str | None
    action: str | None
    enabled: bool
    predefined: bool
    source: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    destination: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    index: int | None
    protocol: str | None
    ip_version: str | None
    connection_state_type: str | None
    connection_states: list[str]
    create_allow_respond: bool | None
    match_ip_sec: bool | None
    match_opposite_protocol: bool | None
    icmp_typename: str | None
    icmp_v6_typename: str | None
    schedule: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    logging: bool | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "action", "enabled", "predefined"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "FirewallRule":
        raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
        connection_states = raw.get("connection_states") or []
        return cls(
            id=raw.get("_id") or raw.get("id"),
            name=raw.get("name"),
            action=raw.get("action"),
            enabled=bool(raw.get("enabled", False)),
            predefined=bool(raw.get("predefined", False)),
            source=raw.get("source"),
            destination=raw.get("destination"),
            index=raw.get("index") or raw.get("rule_index"),
            protocol=raw.get("protocol"),
            ip_version=raw.get("ip_version"),
            connection_state_type=raw.get("connection_state_type"),
            connection_states=list(connection_states) if isinstance(connection_states, list) else [],
            create_allow_respond=raw.get("create_allow_respond"),
            match_ip_sec=raw.get("match_ip_sec"),
            match_opposite_protocol=raw.get("match_opposite_protocol"),
            icmp_typename=raw.get("icmp_typename"),
            icmp_v6_typename=raw.get("icmp_v6_typename"),
            schedule=raw.get("schedule"),
            logging=raw.get("logging"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="A firewall address/port group (V1 /rest/firewallgroup).")
class FirewallGroup:
    id: strawberry.ID | None
    name: str | None
    group_type: str | None
    members: list[str]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "group_type", "members"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "FirewallGroup":
        members = _get(obj, "group_members") or _get(obj, "members") or []
        if not isinstance(members, list):
            members = []
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            group_type=_get(obj, "group_type"),
            members=list(members),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="A firewall zone (V2 /firewall/zone-matrix entry).")
class FirewallZone:
    id: strawberry.ID | None
    name: str | None
    networks: strawberry.scalars.JSON  # type: ignore[name-defined]
    default_policy: str | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "default_policy", "networks"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "FirewallZone":
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            networks=_get(obj, "networks") or _get(obj, "network_ids") or [],
            default_policy=_get(obj, "default_policy") or _get(obj, "default_action"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(
    description=(
        "A rule from the legacy (pre-zone-based) firewall engine, read from V1 "
        "/rest/firewallrule. Distinct from FirewallRule, which models the V2 "
        "zone-based engine: actions are lowercase (accept/drop/reject), rules belong "
        "to a ruleset rather than a zone pair, and source/destination are flat fields "
        "rather than nested objects. Read-only."
    )
)
class LegacyFirewallRule:
    id: strawberry.ID | None
    name: str | None
    ruleset: str | None
    rule_index: int | None
    action: str | None
    enabled: bool | None
    protocol: str | None
    protocol_v6: str | None
    protocol_match_excepted: bool | None
    src_address: str | None
    src_address_ipv6: str | None
    src_port: str | None
    src_mac_address: str | None
    src_firewallgroup_ids: list[str]
    src_networkconf_id: str | None
    src_networkconf_type: str | None
    dst_address: str | None
    dst_address_ipv6: str | None
    dst_port: str | None
    dst_firewallgroup_ids: list[str]
    dst_networkconf_id: str | None
    dst_networkconf_type: str | None
    state_new: bool | None
    state_established: bool | None
    state_related: bool | None
    state_invalid: bool | None
    icmp_typename: str | None
    icmpv6_typename: str | None
    ipsec: str | None
    logging: bool | None
    setting_preference: str | None
    no_edit: bool | None
    no_delete: bool | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["ruleset", "rule_index", "name", "action", "enabled"],
            "sort_default": "rule_index:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "LegacyFirewallRule":
        model = legacy_firewall_rule_from_controller(obj)
        return cls(**model.model_dump())

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(
    description=(
        "User-defined firewall policy ordering for a source/destination zone pair. "
        "Policy IDs in this object are UniFi integration-API UUIDs scoped to the ordering "
        "tool family — use them only with the matching reorder mutation. They do NOT "
        "correspond to the policy IDs returned by other controller-API firewall queries."
    )
)
class FirewallPolicyOrdering:
    ordering: strawberry.scalars.JSON  # type: ignore[name-defined]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "display_columns": ["ordering"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "FirewallPolicyOrdering":
        raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
        return cls(ordering=raw.get("orderedFirewallPolicyIds", raw))

    def to_dict(self) -> dict:
        return asdict(self)
