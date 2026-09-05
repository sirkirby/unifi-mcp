"""Shared field model for Network NAT rules (read + create/update).

- ``NatRule`` — list_nat_rules + get_nat_rule + create_nat_rule + update_nat_rule

The controller stores these under the V2 ``/nat`` collection (see
``managers/nat_manager.py`` for the endpoint table). Field names map 1:1 to the
controller keys; ``_id``, ``is_predefined`` and ``setting_preference`` are
controller-assigned read-only keys.

Values observed on a Network 10.6 controller (rules of every UI variant created
through the endpoint and read back; the controller's 400 bodies enumerate the
closed sets):

- ``type``: ``DNAT``, ``SNAT``, ``MASQUERADE``.
- ``source_filter`` / ``destination_filter`` ``filter_type``: ``NONE``,
  ``ADDRESS_AND_PORT`` (``address`` and/or ``port``), ``FIREWALL_GROUPS``
  (``firewall_group_ids``), ``NETWORK_CONF`` (``network_conf_id``). The
  controller enum also lists ``IID_AND_PORT`` (IPv6); its keys were not read
  back, so it passes through unvalidated.
- ``firewall_group_ids`` is stored as ``[]`` on every filter; ``invert_address``
  and ``invert_port`` are stored on every filter.
- ``protocol``: ``tcp_udp``, ``all``; ``ip_version``: ``IPV4``.
- ``rule_index`` must be unique; a create without one collides with the
  controller's default (``duplicate rule_index``).
- Controller-side rules the validator mirrors: a DNAT needs ``in_interface``,
  ``ip_address`` and a ``destination_filter`` other than ``NONE``; an SNAT needs
  ``out_interface`` and ``ip_address``; a MASQUERADE needs ``out_interface`` and
  may not carry ``ip_address`` or ``port``; a selector under a filter type other
  than the one that uses it is rejected.

A selector (a key the controller only reads under particular enum values) is
declared once, in ``RULE_SELECTORS`` / ``FILTER_SELECTORS``, and that table
drives the requirement check, the reverse check, the read view and the
retirement of stale keys on update. Requirement checks apply to observed values
only; unknown ``type`` or ``filter_type`` values pass through so newer
controllers keep working.

Factory helpers:
- ``from_controller``       — normalise the raw controller dict → NatRule
- ``to_controller_create``  — translate a NatRule → create payload
- ``to_controller_update``  — filter a partial dict to mutable keys only
- ``normalize_nat_create``  — reject unknown keys, normalise enums, validate
- ``normalize_nat_update``  — reject unknown keys, normalise enums
- ``merge_nat_update``      — merge a partial update over the stored rule
- ``nat_rule_error``        — first validation error on a full rule
- ``nat_update_error``      — first error a merged update introduces

``MUTABLE_FIELDS`` will drive the cross-layer symmetry test once the API type lands.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from unifi_core.merge import deep_merge

# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class NatRule(BaseModel):
    """Canonical NAT rule model (read + mutable create/update fields)."""

    # --- read-only ---
    id: Optional[str] = Field(
        default=None,
        description="NAT rule ID (assigned by controller)",
        json_schema_extra={"mutable": False},
    )
    is_predefined: Optional[bool] = Field(
        default=None,
        description="True for controller-managed rules",
        json_schema_extra={"mutable": False},
    )
    setting_preference: Optional[str] = Field(
        default=None,
        description="Controller setting origin ('manual' for UI/API-created rules)",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by create and update) ---
    type: Optional[str] = Field(
        default=None,
        description="Rule type: 'DNAT', 'SNAT' or 'MASQUERADE'",
    )
    description: Optional[str] = Field(default=None, description="Rule name shown in the UI")
    enabled: Optional[bool] = Field(default=None, description="Whether the rule is active")
    rule_index: Optional[int] = Field(
        default=None,
        description="Unique ordering index (NAT is first-match); assigned on create when omitted",
    )
    protocol: Optional[str] = Field(
        default=None,
        description="Match protocol; 'tcp_udp' and 'all' observed, other controller spellings pass through",
    )
    ip_version: Optional[str] = Field(default=None, description="'IPV4' or 'IPV6'")
    in_interface: Optional[str] = Field(default=None, description="Inbound network _id (DNAT)")
    out_interface: Optional[str] = Field(default=None, description="Outbound network _id (SNAT, MASQUERADE)")
    ip_address: Optional[str] = Field(default=None, description="Translation target address (DNAT, SNAT)")
    port: Optional[str] = Field(default=None, description="Translation target port, e.g. '53' or '1000-2000'")
    logging: Optional[bool] = Field(default=None, description="Log matches")
    exclude: Optional[bool] = Field(default=None, description="Exclude matches from translation (unverified)")
    pppoe_use_base_interface: Optional[bool] = Field(
        default=None, description="Match on the PPPoE base interface (PPPoE WAN only, unverified)"
    )
    source_filter: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Source match: filter_type, invert_address, invert_port plus the selector the type uses",
    )
    destination_filter: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Destination match: filter_type, invert_address, invert_port plus the selector the type uses",
    )


# ---------------------------------------------------------------------------
# Field sets and observed vocabularies
# ---------------------------------------------------------------------------

MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in NatRule.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in NatRule.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)

OBSERVED_RULE_TYPES: frozenset[str] = frozenset({"DNAT", "SNAT", "MASQUERADE"})
OBSERVED_FILTER_TYPES: frozenset[str] = frozenset({"NONE", "ADDRESS_AND_PORT", "FIREWALL_GROUPS", "NETWORK_CONF"})

# Selector tables: (key, the enum values that activate it, the value it retires to). The controller
# stores and enforces a selector only under an activating value and rejects it under any other
# observed one. A selector retiring to None is dropped from the document; ``firewall_group_ids``
# retires to ``[]`` because the controller stores that key on every filter.
Selector = tuple[str, frozenset[str], Any]
RULE_SELECTORS: tuple[Selector, ...] = (
    ("ip_address", frozenset({"DNAT", "SNAT"}), None),
    ("port", frozenset({"DNAT", "SNAT"}), None),
)
FILTER_SELECTORS: tuple[Selector, ...] = (
    ("address", frozenset({"ADDRESS_AND_PORT"}), None),
    ("port", frozenset({"ADDRESS_AND_PORT"}), None),
    ("network_conf_id", frozenset({"NETWORK_CONF"}), None),
    ("firewall_group_ids", frozenset({"FIREWALL_GROUPS"}), []),
)
_REQUIRED_BY_TYPE = {
    "DNAT": ("in_interface", "ip_address"),
    "SNAT": ("out_interface", "ip_address"),
    "MASQUERADE": ("out_interface",),
}
_FILTER_SIDES = ("source_filter", "destination_filter")
_PORT_TOKEN = re.compile(r"([0-9]{1,5})(?:-([0-9]{1,5}))?")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# A validation problem: (the key it is about, the message). The key lets an update
# report a problem on a key it touched even when the stored rule had the same message.
Problem = tuple[str, str]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _inactive_selectors(selectors: tuple[Selector, ...], enum_value: Any) -> List[Selector]:
    """The selectors the controller ignores under an observed enum value."""
    return [s for s in selectors if enum_value not in s[1]]


def _hide_inactive(doc: Any, selectors: tuple[Selector, ...], enum_key: str, observed: frozenset[str]) -> Any:
    """Drop set selectors the controller ignores under the document's observed enum value."""
    if not isinstance(doc, dict) or not isinstance(doc.get(enum_key), str) or doc[enum_key] not in observed:
        return doc
    inactive = {s[0] for s in _inactive_selectors(selectors, doc[enum_key])}
    return {k: v for k, v in doc.items() if not (k in inactive and v)}


def _retire_stale(
    stored: Dict[str, Any],
    update: Dict[str, Any],
    merged: Dict[str, Any],
    selectors: tuple[Selector, ...],
    enum_key: str,
    observed: frozenset[str],
) -> None:
    """Reset selectors a partial update deactivates, in place on ``merged``.

    Keys the update sets itself are left alone; an unobserved enum value
    retires nothing because its selectors are unknown.
    """
    value = update.get(enum_key)
    if not isinstance(value, str) or value not in observed:
        return
    for key, _, empty in _inactive_selectors(selectors, value):
        if key in update or not stored.get(key):
            continue
        if empty is None:
            merged.pop(key, None)
        else:
            merged[key] = empty


def _drop_none(doc: Any) -> Any:
    return {k: v for k, v in doc.items() if v is not None} if isinstance(doc, dict) else doc


def _port_error(label: str, value: Any) -> str | None:
    """Validate a port string: comma-separated ports or ``low-high`` ranges, 1-65535, ASCII digits, no spaces."""
    if not isinstance(value, str) or not value:
        return "%s %r must be a non-empty string such as '53' or '1000-2000'." % (label, value)
    for token in value.split(","):
        match = _PORT_TOKEN.fullmatch(token)
        if not match:
            return "%s %r must be a comma-separated list of ports or low-high ranges with no spaces." % (label, value)
        low = int(match.group(1))
        high = int(match.group(2)) if match.group(2) else low
        if not (1 <= low <= 65535 and 1 <= high <= 65535) or low > high:
            return "%s %r must use ports 1-65535 with ranges written low-high." % (label, value)
    return None


def _inactive_selector_problems(
    doc: Dict[str, Any], selectors: tuple[Selector, ...], enum_key: str, prefix: str
) -> List[Problem]:
    """One problem per set selector the controller would ignore under the document's enum value."""
    return [
        (
            prefix + key,
            "%s%s must be one of %s when %s%s is set, not %r."
            % (prefix, enum_key, " or ".join("'%s'" % a for a in sorted(activators)), prefix, key, doc[enum_key]),
        )
        for key, activators, _ in _inactive_selectors(selectors, doc[enum_key])
        if doc.get(key)
    ]


def _filter_problems(side: str, flt: Any) -> List[Problem]:
    """Every problem on one source/destination filter, in check order."""
    if flt is None:
        return []
    if not isinstance(flt, dict):
        return [(side, "%s must be an object with filter_type." % side)]
    filter_type = flt.get("filter_type")
    if not filter_type:
        return [(side + ".filter_type", "%s.filter_type is required." % side)]
    if not isinstance(filter_type, str):
        return [(side + ".filter_type", "%s.filter_type %r must be a string." % (side, filter_type))]
    if filter_type not in OBSERVED_FILTER_TYPES:
        return []
    problems: List[Problem] = []
    required = [key for key, activators, _ in FILTER_SELECTORS if filter_type in activators]
    if required and not any(flt.get(key) for key in required):
        problems.append(
            (
                side + ".filter_type",
                "%s is required when filter_type is '%s'."
                % (" or ".join("%s.%s" % (side, key) for key in required), filter_type),
            )
        )
    if filter_type == "ADDRESS_AND_PORT" and flt.get("port") is not None:
        if error := _port_error("%s.port" % side, flt["port"]):
            problems.append((side + ".port", error))
    problems.extend(_inactive_selector_problems(flt, FILTER_SELECTORS, "filter_type", side + "."))
    return problems


def _rule_problems(fields: Dict[str, Any]) -> List[Problem]:
    """Every validation problem on a full rule document, in check order."""
    problems: List[Problem] = []
    rule_type = fields.get("type")
    if rule_type is not None and not isinstance(rule_type, str):
        problems.append(("type", "type %r must be a string." % (rule_type,)))
        rule_type = None
    elif not rule_type:
        problems.append(("type", "type is required: 'DNAT', 'SNAT' or 'MASQUERADE'."))
    for key in _REQUIRED_BY_TYPE.get(rule_type, ()):
        if not fields.get(key):
            problems.append((key, "%s is required when type is '%s'." % (key, rule_type)))
    if rule_type == "DNAT":
        dest_type = _get(fields.get("destination_filter"), "filter_type")
        if not dest_type or dest_type == "NONE":
            problems.append(
                (
                    "destination_filter.filter_type",
                    "destination_filter.filter_type must be a match other than 'NONE' when type is 'DNAT'.",
                )
            )
    if rule_type in OBSERVED_RULE_TYPES:
        problems.extend(_inactive_selector_problems(fields, RULE_SELECTORS, "type", ""))
    if fields.get("port") is not None and (error := _port_error("port", fields["port"])):
        problems.append(("port", error))
    index = fields.get("rule_index")
    if index is not None and (not isinstance(index, int) or isinstance(index, bool)):
        problems.append(("rule_index", "rule_index %r must be an integer." % (index,)))
    for side in _FILTER_SIDES:
        problems.extend(_filter_problems(side, fields.get(side)))
    return problems


def _touched_keys(current: Dict[str, Any], merged: Dict[str, Any]) -> set[str]:
    """Top-level keys, and ``side.key`` filter keys, whose value differs between the two documents."""
    touched = {k for k in set(current) | set(merged) if current.get(k) != merged.get(k)}
    for side in _FILTER_SIDES:
        before, after = current.get(side), merged.get(side)
        if isinstance(before, dict) and isinstance(after, dict):
            touched |= {"%s.%s" % (side, k) for k in set(before) | set(after) if before.get(k) != after.get(k)}
    return touched


# ---------------------------------------------------------------------------
# Public factory helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> NatRule:
    """Build a NatRule from a controller API response dict.

    Selectors stored under a type or filter_type that does not use them are
    hidden, since the controller ignores them.
    """
    if isinstance(raw, dict):
        raw = _hide_inactive(raw, RULE_SELECTORS, "type", OBSERVED_RULE_TYPES)
    return NatRule(
        id=_get(raw, "_id") or _get(raw, "id"),
        is_predefined=_get(raw, "is_predefined"),
        setting_preference=_get(raw, "setting_preference"),
        type=_get(raw, "type"),
        description=_get(raw, "description"),
        enabled=_get(raw, "enabled"),
        rule_index=_get(raw, "rule_index"),
        protocol=_get(raw, "protocol"),
        ip_version=_get(raw, "ip_version"),
        in_interface=_get(raw, "in_interface"),
        out_interface=_get(raw, "out_interface"),
        ip_address=_get(raw, "ip_address"),
        port=_get(raw, "port"),
        logging=_get(raw, "logging"),
        exclude=_get(raw, "exclude"),
        pppoe_use_base_interface=_get(raw, "pppoe_use_base_interface"),
        source_filter=_hide_inactive(
            _get(raw, "source_filter"), FILTER_SELECTORS, "filter_type", OBSERVED_FILTER_TYPES
        ),
        destination_filter=_hide_inactive(
            _get(raw, "destination_filter"), FILTER_SELECTORS, "filter_type", OBSERVED_FILTER_TYPES
        ),
    )


def reject_unknown_fields(fields: Dict[str, Any]) -> None:
    """Raise ``ValueError`` if any key is not an accepted (mutable) field."""
    unknown = set(fields) - MUTABLE_FIELDS
    if unknown:
        raise ValueError(f"Unknown or read-only fields: {sorted(unknown)}. Allowed fields: {sorted(MUTABLE_FIELDS)}")


def to_controller_create(model: NatRule) -> Dict[str, Any]:
    """Produce a controller create payload from a NatRule (mutable, non-None fields)."""
    return to_controller_update(model.model_dump())


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only mutable, recognised keys.

    Read-only fields and unrecognised keys are dropped. ``None`` values are
    dropped so an omitted field never clears controller state.
    """
    return {k: v for k, v in fields.items() if k in MUTABLE_FIELDS and v is not None}


def normalize_nat_enums(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Upper-case ``type``, ``ip_version`` and each filter's ``filter_type``; lower-case ``protocol``."""
    normalized = dict(fields)
    for key in ("type", "ip_version"):
        if isinstance(normalized.get(key), str):
            normalized[key] = normalized[key].strip().upper()
    if isinstance(normalized.get("protocol"), str):
        normalized["protocol"] = normalized["protocol"].strip().lower()
    for side in _FILTER_SIDES:
        flt = normalized.get(side)
        if isinstance(flt, dict) and isinstance(flt.get("filter_type"), str):
            normalized[side] = {**flt, "filter_type": flt["filter_type"].strip().upper()}
    return normalized


def nat_rule_error(fields: Dict[str, Any]) -> str | None:
    """Return the first validation error on a full rule document, or ``None``.

    Requirement checks cover the rule types and filter types observed on live
    controllers; other values pass through untouched.
    """
    return next((message for _, message in _rule_problems(fields)), None)


def normalize_nat_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Validate keys and value types and normalise enums on a public partial update.

    Rejects unknown or read-only keys and wrong value types (``ValueError``;
    pydantic's strict mode does the type check, so ``"3"`` is not an int and
    ``"yes"`` is not a bool), and drops ``None`` values at the top level and
    inside the filters. Validation of the rule itself needs the stored
    document; see :func:`merge_nat_update` and :func:`nat_update_error`.
    """
    reject_unknown_fields(fields)
    payload = to_controller_update(normalize_nat_enums(fields))
    NatRule.model_validate(payload, strict=True)
    for side in _FILTER_SIDES:
        if side in payload:
            payload[side] = _drop_none(payload[side])
    return payload


def normalize_nat_create(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Validate keys, normalise enums and validate a public create payload (``ValueError`` on any problem)."""
    payload = normalize_nat_update(fields)
    if error := nat_rule_error(payload):
        raise ValueError(error)
    return payload


def merge_nat_update(current: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a normalised partial update over the stored rule into the document to PUT.

    Filters deep-merge so sibling keys survive. A selector the update
    deactivates (a filter's ``filter_type`` moved away from the value that uses
    it, or ``type`` moved to ``MASQUERADE`` while a translation target is
    stored) is dropped, and ``None`` inside a filter is dropped, so nothing the
    controller would ignore or reject is sent.
    """
    merged = deep_merge(current, update)
    _retire_stale(current, update, merged, RULE_SELECTORS, "type", OBSERVED_RULE_TYPES)
    for side in _FILTER_SIDES:
        flt, stored_flt = update.get(side), current.get(side)
        if isinstance(flt, dict) and isinstance(stored_flt, dict):
            _retire_stale(stored_flt, flt, merged[side], FILTER_SELECTORS, "filter_type", OBSERVED_FILTER_TYPES)
        if side in merged:
            merged[side] = _drop_none(merged[side])
    return merged


def nat_update_error(current: Dict[str, Any], merged: Dict[str, Any]) -> str | None:
    """Return the first validation error a merged update introduces.

    A problem is reported when it concerns a key the update changed, or when the
    stored rule did not already have it. Problems the stored rule already has on
    keys the update left alone (state this project did not author) are not held
    against the update.
    """
    touched = _touched_keys(current, merged)
    preexisting = set(_rule_problems(current))
    return next(
        (message for key, message in _rule_problems(merged) if key in touched or (key, message) not in preexisting),
        None,
    )
