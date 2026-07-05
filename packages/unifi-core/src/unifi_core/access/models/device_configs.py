"""Domain model + boundary helpers for Access device configs.

A UniFi Access device carries a ``configs[]`` array in the controller's
``devices/topology4`` response — the per-device settings the Access web UI
edits (voice greeting, sounds, display, wiring, etc.). Each entry is a
``{device_id, key, value, tag, update_time, create_time}`` record.

``DeviceConfigEntry`` mirrors the Strawberry type in
``unifi_api.graphql.types.access.device_configs``.

The domain model is lossless — it carries ``value`` verbatim, including
secrets. Redaction is a response-boundary concern applied by the serving
surface via :func:`redact_config_entries` (mirrors the Credential model).

Write helpers (:func:`validate_config_updates`, :func:`build_config_write_body`)
back ``access_update_device_config``: the caller supplies ``{key: value}``
pairs, keys are validated against the device's *live* configs, and each
entry's ``tag`` is looked up from that live config — so callers never guess a
tag and cannot introduce keys the device does not already expose. Credential-
and secret-named keys are refused: this tool edits device settings, not
secrets.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from unifi_core.redaction import REDACTED, is_sensitive_key

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Config entries tagged as credentials carry live secrets (ssh_password,
#: nacl_private_key, ...) and are never exposed or written.
CREDENTIAL_TAG = "credential"

#: Camera-class Access readers (e.g. the G6 Pro Entry) carry a 24-hex
#: Protect-style device id and require ``is_camera=true`` on the config PUT;
#: hubs use a MAC-style id and require ``is_camera=false``.
_PROTECT_STYLE_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")


# ---------------------------------------------------------------------------
# Pydantic domain model
# ---------------------------------------------------------------------------


class DeviceConfigEntry(BaseModel):
    """A single per-device config key/value entry (read-only projection)."""

    device_id: Optional[str] = Field(default=None, description="Owning device UUID")
    key: Optional[str] = Field(default=None, description="Config key name")
    value: Optional[str] = Field(default=None, description="Config value (redacted at egress when sensitive)")
    tag: Optional[str] = Field(
        default=None,
        description="Config category (device_setting, device_extra, hub_action, hub_power, wiring_state, credential)",
    )
    update_time: Optional[str] = Field(default=None, description="Last-update timestamp (ISO 8601 string)")
    create_time: Optional[str] = Field(default=None, description="Creation timestamp (ISO 8601 string)")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Public factory + boundary helpers
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> DeviceConfigEntry:
    """Build a :class:`DeviceConfigEntry` from a manager dict or object.

    Lossless — the raw ``value`` (secret or not) is carried through. Redaction
    is applied later by :func:`redact_config_entries` at the serving boundary.
    """
    return DeviceConfigEntry(
        device_id=_get(raw, "device_id"),
        key=_get(raw, "key"),
        value=_get(raw, "value"),
        tag=_get(raw, "tag"),
        update_time=_get(raw, "update_time"),
        create_time=_get(raw, "create_time"),
    )


def is_sensitive_config(key: Any, tag: Any) -> bool:
    """Return true when a config entry carries secret material.

    An entry is sensitive when the controller tags it ``credential`` OR when
    its key name trips the shared secret vocabulary (:func:`is_sensitive_key`).
    Routing key-name detection through the shared helper keeps the decision
    consistent with the rest of the redaction surface.
    """
    if tag == CREDENTIAL_TAG:
        return True
    return is_sensitive_key(key)


def redact_config_entries(entries: List[Dict[str, Any]], *, redact_sensitive: bool = True) -> List[Dict[str, Any]]:
    """Return a copy of ``entries`` with sensitive ``value`` fields redacted.

    Each entry is a dict carrying ``key``/``value``/``tag``. A ``value`` is
    replaced with the redaction marker when the entry is sensitive (see
    :func:`is_sensitive_config`) and the value is present. ``None`` values are
    left as-is (nothing to hide). The input list is not mutated.
    """
    out: List[Dict[str, Any]] = []
    for entry in entries:
        projected = dict(entry)
        if (
            redact_sensitive
            and projected.get("value") is not None
            and is_sensitive_config(projected.get("key"), projected.get("tag"))
        ):
            projected["value"] = REDACTED
        out.append(projected)
    return out


def is_camera_device_id(device_id: Any) -> bool:
    """Return true for camera-class readers (24-hex Protect-style device id).

    Verified against current firmware: the config PUT requires
    ``is_camera=true`` for camera-class readers (e.g. the G6 Pro Entry, whose
    device id is a 24-hex Protect-style string) and ``is_camera=false`` for
    hubs (MAC-style id). Used as the default when the caller does not pin
    ``is_camera`` explicitly.
    """
    if not isinstance(device_id, str):
        return False
    return bool(_PROTECT_STYLE_ID_RE.match(device_id))


def validate_config_updates(
    updates: Dict[str, Any], current_by_key: Dict[str, Dict[str, Any]]
) -> Tuple[bool, Optional[str]]:
    """Validate a ``{key: value}`` update against the device's live configs.

    Rules:
      * ``updates`` must be non-empty.
      * every key must already exist in ``current_by_key`` (no novel keys).
      * credential-tagged or secret-named keys are refused (this tool edits
        device settings, not secrets).

    Returns ``(True, None)`` when valid, else ``(False, message)``.
    """
    if not updates:
        return False, "No config updates supplied."

    writable = sorted(k for k, e in current_by_key.items() if not is_sensitive_config(k, (e or {}).get("tag")))

    unknown = [k for k in updates if k not in current_by_key]
    if unknown:
        return (
            False,
            f"Unknown config key(s): {sorted(unknown)}. Writable keys on this device: {writable}",
        )

    protected = [k for k in updates if is_sensitive_config(k, (current_by_key[k] or {}).get("tag"))]
    if protected:
        return (
            False,
            f"Refusing to write credential/secret config key(s): {sorted(protected)}.",
        )

    return True, None


def build_config_write_body(updates: Dict[str, Any], current_by_key: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build the controller PUT body: a list of ``{key, tag, value}`` entries.

    The ``tag`` for each key is taken from the device's live config so the
    caller never has to supply it. Values are coerced to strings (the
    controller stores config values as strings). Assumes ``updates`` has
    already passed :func:`validate_config_updates`.

    The body contains ONLY the changed keys — this is an upsert, not a
    full-collection replace. Verified against current firmware: the Access web
    UI itself PUTs partial ``configs`` arrays for a single-setting change (e.g.
    a lone ``[{greeting_text, hello}]``), and unlisted entries — including the
    device's ``credential``-tagged connectivity secrets — are preserved. This
    is deliberately NOT a fetch-merge-put of the whole array: echoing every
    entry back would re-send those credential secrets to the controller, which
    the read/write redaction+refusal design exists to avoid.
    """
    return [
        {"key": key, "tag": (current_by_key[key] or {}).get("tag"), "value": str(value)}
        for key, value in updates.items()
    ]
