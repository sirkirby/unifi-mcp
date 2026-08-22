"""Shared field model for MAC ACL rules.

Single source of truth for list/get output and create/update input,
imported by both the MCP tool layer (``apps/network``) and the API
server (``apps/api``). Translation helpers convert between this
model's flat field names and the controller API's nested
traffic_source/traffic_destination structure.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator

from unifi_core.mac import normalize_mac, normalize_mac_list

# A MAC netmask is the number of leading bits that must match (the UI's
# optional "Netmask" dropdown — e.g. 24 = vendor OUI, 48 = the complete MAC).
# The controller stores it as a 6-octet MAC-format bitmask. The UI offers
# 9..48, but the controller accepts the full 0..48 range (verified against a
# live UDM-Pro-Max, Network 10.x), so we allow that range.
_NETMASK_BITS = 48
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _check_netmask_range(bits: Optional[int]) -> Optional[str]:
    """Return an error message if ``bits`` is out of the accepted range, else None.

    None (no netmask) is allowed. Single source of truth for the range rule,
    shared by the model field_validator, validate_update_fields, and the
    converter below so they can never disagree.
    """
    if bits is None:
        return None
    if not 0 <= bits <= _NETMASK_BITS:
        return f"netmask must be between 0 and {_NETMASK_BITS} (bits of a MAC address), got {bits!r}"
    return None


def netmask_to_mac_mask(bits: int) -> str:
    """Convert a netmask bit-count (0-48) to a 6-octet MAC-format bitmask string.

    Raises ValueError on an out-of-range bit-count rather than silently
    producing a wrong mask, so any caller that reaches here without validating
    fails loudly instead of writing a match-everything/garbage ACL.
    """
    err = _check_netmask_range(bits)
    if err is not None:
        raise ValueError(err)
    mask_int = ((1 << bits) - 1) << (_NETMASK_BITS - bits)
    return ":".join(f"{(mask_int >> (40 - 8 * i)) & 0xFF:02x}" for i in range(6))


def mac_mask_to_netmask(mask: Any) -> Optional[int]:
    """Convert a MAC-format bitmask string to a netmask bit-count.

    Returns None for anything that is not a strictly-formatted 6-octet hex mask
    (non-string, wrong octet count, any token that is not exactly two hex digits —
    so ``0x``-prefixed, single-digit, or whitespace-padded tokens are rejected),
    or for a well-formed but non-contiguous mask (a value the controller accepts
    via the API but the UI's prefix dropdown cannot represent). The raw bitmask
    remains available on the read-only ``*_mac_mask`` field.
    """
    if not isinstance(mask, str):
        return None
    tokens = mask.split(":")
    if len(tokens) != 6:
        return None
    if not all(len(t) == 2 and all(c in _HEX_DIGITS for c in t) for t in tokens):
        return None
    bits = "".join(f"{int(t, 16):08b}" for t in tokens)
    stripped = bits.rstrip("0")
    if "0" in stripped:  # a zero before the final set bit → non-contiguous
        return None
    return len(stripped)


def read_mask_fields(traffic: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
    """Derive (raw_mac_mask, netmask) from a controller traffic_source/destination dict.

    Single source of truth for the read-side mask derivation, shared by the
    pydantic ``from_controller`` and the GraphQL ``AclRule.from_manager_output``
    so the two layers can never report a different netmask for the same rule.
    """
    mask = traffic.get("mac_mask")
    if not isinstance(mask, str) or not mask:
        return None, None
    return mask, mac_mask_to_netmask(mask)


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
    source_netmask: Optional[int] = Field(
        default=None,
        description=(
            "Optional netmask for source_macs — the number of leading bits that must match, as chosen "
            "by the 'Netmask' dropdown in the UI (e.g. 24 matches the vendor OUI, 48 matches the "
            "complete MAC). Omit (null) for an exact match. The UI offers 9-48; 0-48 is accepted, but "
            "do NOT pass 0 to mean 'no mask' — 0 matches ANY MAC (every bit is wildcarded)."
        ),
    )
    destination_netmask: Optional[int] = Field(
        default=None,
        description=(
            "Optional netmask for destination_macs — the number of leading bits that must match, as "
            "chosen by the 'Netmask' dropdown in the UI (e.g. 24 matches the vendor OUI, 48 matches the "
            "complete MAC). Omit (null) for an exact match. The UI offers 9-48; 0-48 is accepted, but "
            "do NOT pass 0 to mean 'no mask' — 0 matches ANY MAC (every bit is wildcarded)."
        ),
    )
    # Raw bitmask exactly as stored on the controller. Read-only and set via
    # *_netmask; surfaced so the true stored value is always visible — including
    # a non-contiguous mask the API permits but the UI cannot express, where the
    # corresponding *_netmask is null.
    source_mac_mask: Optional[str] = Field(
        default=None,
        description=(
            "Raw MAC-format bitmask stored for source_macs (e.g. 'ff:ff:ff:00:00:00'). "
            "Read-only; set via source_netmask."
        ),
        json_schema_extra={"mutable": False},
    )
    destination_mac_mask: Optional[str] = Field(
        default=None,
        description=(
            "Raw MAC-format bitmask stored for destination_macs (e.g. 'ff:ff:ff:00:00:00'). "
            "Read-only; set via destination_netmask."
        ),
        json_schema_extra={"mutable": False},
    )

    @field_validator("source_netmask", "destination_netmask")
    @classmethod
    def _validate_netmask(cls, v: Optional[int]) -> Optional[int]:
        err = _check_netmask_range(v)
        if err is not None:
            raise ValueError(err)
        return v


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
    # Guard against a null/non-dict traffic block (matches the defensive coercion in the
    # GraphQL AclRule.from_manager_output): a controller returning "traffic_source": null
    # must not crash list/get with an AttributeError, and a null specific_mac_addresses
    # must not reach the List[str] field as None.
    source = raw.get("traffic_source")
    destination = raw.get("traffic_destination")
    source = source if isinstance(source, dict) else {}
    destination = destination if isinstance(destination, dict) else {}
    source_mask, source_netmask = read_mask_fields(source)
    destination_mask, destination_netmask = read_mask_fields(destination)

    return AclRule(
        id=raw.get("_id"),
        name=raw.get("name", ""),
        acl_index=raw.get("acl_index", 0),
        action=raw.get("action", "BLOCK"),
        enabled=raw.get("enabled", True),
        network_id=raw.get("mac_acl_network_id", ""),
        source_type=source.get("type"),
        source_macs=source.get("specific_mac_addresses") or [],
        source_mac_mask=source_mask,
        source_netmask=source_netmask,
        destination_type=destination.get("type"),
        destination_macs=destination.get("specific_mac_addresses") or [],
        destination_mac_mask=destination_mask,
        destination_netmask=destination_netmask,
    )


def build_acl_rule(args: Dict[str, Any]) -> "AclRule":
    """Construct an AclRule from flat user-facing create args.

    Single source of truth for create-arg → model mapping, shared by the MCP
    tool (``tools/acl.py:create_acl_rule``) and the API dispatch translator
    (``dispatch_overrides.py:_translate_acl_create``) so the two surfaces can
    never drift (e.g. one accepting a field the other silently drops). Raises
    pydantic ``ValidationError`` on invalid input; callers translate that into
    their surface's error contract.
    """
    return AclRule(
        name=args["name"],
        acl_index=args["acl_index"],
        action=str(args["action"]).upper(),
        enabled=args.get("enabled", True),
        network_id=args["network_id"],
        source_macs=args.get("source_macs") or [],
        destination_macs=args.get("destination_macs") or [],
        source_netmask=args.get("source_netmask"),
        destination_netmask=args.get("destination_netmask"),
    )


def _create_side(macs: List[str], netmask: Optional[int], raw_mask: Optional[str]) -> Dict[str, Any]:
    """Build a full traffic_source/destination block for a create payload.

    Mask precedence: the mutable ``netmask`` wins; otherwise fall back to the
    read-only ``raw_mask`` (set by ``from_controller``) so a recreate of a rule
    whose mask is non-contiguous — and therefore has ``netmask=None`` — does not
    silently drop the mask. Omit the key entirely when neither is present
    (exact match), matching how the controller stores an unmasked rule.
    """
    side: Dict[str, Any] = {
        "ips_or_subnets": [],
        "network_ids": [],
        "ports": [],
        # Lowercased at the boundary: the controller stores these lowercase, so an
        # uppercase create would not round-trip against a later list. An entry
        # that normalizes to nothing passes through unchanged rather than
        # becoming None.
        "specific_mac_addresses": [normalize_mac(m) or m for m in macs],
        "type": "CLIENT_MAC",
    }
    if netmask is not None:
        side["mac_mask"] = netmask_to_mac_mask(netmask)
    elif raw_mask:
        side["mac_mask"] = raw_mask
    return side


def to_controller_create(rule: AclRule) -> Dict[str, Any]:
    """Build a controller API create payload from an AclRule."""
    return {
        "name": rule.name,
        "acl_index": rule.acl_index,
        "action": rule.action,
        "enabled": rule.enabled,
        "mac_acl_network_id": rule.network_id,
        "specific_enforcers": [],
        "traffic_source": _create_side(rule.source_macs, rule.source_netmask, rule.source_mac_mask),
        "traffic_destination": _create_side(rule.destination_macs, rule.destination_netmask, rule.destination_mac_mask),
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
        # action is a case-insensitive Literal — normalize before the strict check so the
        # update path accepts lowercase like the create path (build_acl_rule does .upper()).
        check_value = value.upper() if field_name == "action" and isinstance(value, str) else value
        try:
            TypeAdapter(field_info.annotation).validate_python(check_value, strict=True)
        except ValidationError as e:
            err = e.errors()[0]
            return False, f"Invalid value for '{field_name}': {err['msg']}"
        if field_name in ("source_netmask", "destination_netmask"):
            range_err = _check_netmask_range(value)
            if range_err is not None:
                return False, f"Invalid value for '{field_name}': {range_err}"
    return True, None


CLEAR_NETMASK_FIELDS = frozenset({"clear_source_netmask", "clear_destination_netmask"})


def _update_side(fields: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    """Build a PARTIAL traffic_source/destination block for an update payload.

    The manager deep-merges this into the fetched rule, so omitted sub-keys
    (type, the existing mask when only MACs change, or the existing MACs when
    only the mask changes) are preserved.

    Mask handling:
    - ``<prefix>_netmask`` set to a value writes the corresponding bitmask.
    - ``<prefix>_netmask`` of None / absent is "leave unchanged" (a safe no-op,
      so round-tripping a listed rule whose netmask is null is non-destructive).
    - ``clear_<prefix>_netmask`` True emits ``mac_mask: None`` — a sentinel the
      manager turns into key REMOVAL after the deep-merge (the controller rejects
      an empty mac_mask with HTTP 400, and deep-merge cannot itself delete a key,
      so the manager pops it). This is the explicit, unambiguous way to widen a
      prefix rule back to an exact match without delete+recreate.
    """
    side: Dict[str, Any] = {}
    macs_key = f"{prefix}_macs"
    netmask_key = f"{prefix}_netmask"
    clear_key = f"clear_{prefix}_netmask"
    if macs_key in fields:
        side["specific_mac_addresses"] = normalize_mac_list(fields[macs_key])
    if fields.get(clear_key):
        side["mac_mask"] = None  # sentinel → manager removes the key, clearing the mask
    elif fields.get(netmask_key) is not None:
        side["mac_mask"] = netmask_to_mac_mask(fields[netmask_key])
    if side:
        side["type"] = "CLIENT_MAC"
    return side


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a partial update dict from model field names to controller shape.

    Only includes fields the caller provided.
    """
    result: Dict[str, Any] = {}

    source = _update_side(fields, "source")
    if source:
        result["traffic_source"] = source
    destination = _update_side(fields, "destination")
    if destination:
        result["traffic_destination"] = destination

    for model_key, controller_key in UPDATE_FIELD_MAP.items():
        if model_key in fields:
            value = fields[model_key]
            if model_key == "action" and isinstance(value, str):
                value = value.upper()  # canonical form, matching the create path
            result[controller_key] = value

    return result


UPDATE_FIELD_MAP: Dict[str, str] = {
    "name": "name",
    "acl_index": "acl_index",
    "action": "action",
    "enabled": "enabled",
    "network_id": "mac_acl_network_id",
}

MAC_TRANSLATED_FIELDS = frozenset({"source_macs", "destination_macs", "source_netmask", "destination_netmask"})
