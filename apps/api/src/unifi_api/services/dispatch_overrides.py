"""Static dispatch overrides for tools the AST walker can't resolve correctly.

The Phase 2 dispatch builder in :mod:`unifi_api.services.actions` AST-walks
tool modules and records the **first** ``await <singleton>.<method>(...)``
call inside each ``@server.tool`` body. That works for ~95% of tools, but
fails for two structural patterns:

1. **Lookup-then-act with state-dependent preview** (network/clients): the
   tool body genuinely needs the current resource state to render a useful
   preview (current device name before reboot, the old WLAN config before
   update, the toggle's current enabled flag to compute new state). Refactor
   would strip a real preview-UX feature, so the tool keeps its 2-call body
   and we override dispatch to point at the mutation method.

2. **Preview/execute split** (protect/access): managers expose two methods —
   ``X(id)`` returns preview state, ``apply_X(id)`` executes the mutation.
   Both are awaited from the tool body depending on ``confirm``. AST captures
   the first one (typically ``X``); we override to point at ``apply_X``.

Each entry is ``tool_name → (manager_attr, method)`` exactly matching the
:class:`DispatchEntry` shape the dispatcher consumes. Overrides are applied
*after* the AST walk in :func:`build_dispatch_table`, so adding an entry
here always wins over the AST-derived one.

PR4 of the manager-owned-existence-checks refactor (siblings #172 #173 #175).

Argument translators
--------------------
A second mechanism, :data:`DISPATCH_ARG_TRANSLATORS`, addresses a different
mismatch: tools whose body translates flat user-facing kwargs into a
controller-shaped payload before calling the manager. The AST walker
correctly maps the tool to the manager method, but the dispatcher's default
``await method(**args)`` skips the tool body's translation step. Register a
translator that converts the action endpoint's ``args`` dict into the
``(positional, keyword)`` shape the manager expects. Phase 0 seeded this
for ACL create/update; other tools that share the shape-translation pattern
should follow the same approach as they migrate to the shared field-symmetry
model.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Callable

from unifi_core.network.read_views import (
    shape_alerts,
    shape_client_details,
    shape_client_list,
    shape_dashboard,
    shape_device_details,
    shape_device_list,
    shape_firewall_policy_list,
    shape_network_details,
    shape_network_list,
    shape_rogue_ap_list,
    shape_wlan_list,
)

from unifi_api.services.action_results import ShapedReadResult

# Format: tool_name -> (manager_attr, method_name)
DISPATCH_OVERRIDES: dict[str, tuple[str, str]] = {
    # =========================================================================
    # Network — lookup-then-act tools whose preview needs current state
    # =========================================================================
    # Client mutations: tool pre-fetches via get_client_details for preview
    # enrichment (name, current state). Manager already validates existence
    # internally per PR1.
    "unifi_block_client": ("client_manager", "block_client"),
    "unifi_unblock_client": ("client_manager", "unblock_client"),
    "unifi_rename_client": ("client_manager", "rename_client"),
    "unifi_force_reconnect_client": ("client_manager", "force_reconnect_client"),
    "unifi_authorize_guest": ("client_manager", "authorize_guest"),
    "unifi_unauthorize_guest": ("client_manager", "unauthorize_guest"),
    "unifi_set_client_ip_settings": ("client_manager", "set_client_ip_settings"),
    "unifi_forget_client": ("client_manager", "forget_client"),
    # list_clients branches between get_all_clients (offline+history) and
    # get_clients (online only) on the include_offline parameter. Default path
    # is the online list.
    "unifi_list_clients": ("client_manager", "get_clients"),
    # Network/WLAN/AP-group mutations: preview pre-fetches for current config.
    "unifi_update_network": ("network_manager", "update_network"),
    "unifi_delete_network": ("network_manager", "delete_network"),
    "unifi_update_wlan": ("network_manager", "update_wlan"),
    "unifi_toggle_wlan": ("network_manager", "toggle_wlan"),
    "unifi_delete_wlan": ("network_manager", "delete_wlan"),
    "unifi_update_ap_group": ("network_manager", "update_ap_group"),
    "unifi_delete_ap_group": ("network_manager", "delete_ap_group"),
    # Gateway/SNMP settings updates pre-fetch current state for previews.
    "unifi_update_gateway_settings": ("gateway_settings_manager", "update_gateway_settings"),
    "unifi_update_snmp_settings": ("system_manager", "update_settings"),
    # Firewall: tool layer pre-fetches list to find policy by id.
    "unifi_toggle_firewall_policy": ("firewall_manager", "toggle_firewall_policy"),
    "unifi_get_firewall_policy_details": ("firewall_manager", "get_firewall_policy_by_id"),
    "unifi_update_firewall_policy": ("firewall_manager", "update_firewall_policy"),
    "unifi_reorder_firewall_policies": ("firewall_manager", "reorder_firewall_policies"),
    "unifi_update_firewall_zone": ("firewall_manager", "update_firewall_zone"),
    "unifi_delete_firewall_zone": ("firewall_manager", "delete_firewall_zone"),
    # Toggle tools: tool body needs current enabled flag to compute new state.
    "unifi_toggle_port_forward": ("firewall_manager", "toggle_port_forward"),
    "unifi_toggle_qos_rule_enabled": ("qos_manager", "toggle_qos_rule_enabled"),
    "unifi_toggle_oon_policy": ("oon_manager", "toggle_oon_policy"),
    "unifi_toggle_traffic_route": ("traffic_route_manager", "toggle_traffic_route"),
    # update_traffic_route now pre-fetches the route via get_traffic_route_details
    # to render a current-vs-proposed preview, so the AST walker captures the read
    # method first. Pin dispatch to the mutation method.
    "unifi_update_traffic_route": ("traffic_route_manager", "update_traffic_route"),
    # update_dynamic_dns pre-fetches the entry via get_dynamic_dns to render a
    # current-vs-proposed preview, so the AST walker captures the read method
    # first. Pin dispatch to the mutation method.
    "unifi_update_dynamic_dns": ("dynamic_dns_manager", "update_dynamic_dns"),
    # update_device_radio: tool needs current radio_table to identify target band.
    "unifi_update_device_radio": ("device_manager", "update_device_radio"),
    # PDU and port-forward updates both pre-fetch current state for preview.
    "unifi_set_outlet_state": ("device_manager", "set_outlet_state"),
    "unifi_update_port_forward": ("firewall_manager", "update_port_forward"),
    # VPN state/delete tools pre-fetch details for live-state previews.
    "unifi_update_vpn_client_state": ("vpn_manager", "update_vpn_client_state"),
    "unifi_delete_vpn_client": ("vpn_manager", "delete_vpn_client"),
    "unifi_update_vpn_server_state": ("vpn_manager", "update_vpn_server_state"),
    # Stats: tool combines existence check on client/device with stats fetch.
    "unifi_get_device_stats": ("stats_manager", "get_device_stats_for_identifier"),
    "unifi_get_client_stats": ("stats_manager", "get_client_stats_for_identifier"),
    "unifi_get_top_clients": ("stats_manager", "get_top_clients"),
    # Event tools obtain their Core manager through a lazy helper rather than
    # importing a runtime singleton, so the source AST has no direct binding.
    "unifi_list_events": ("event_manager", "get_events"),
    "unifi_list_alarms": ("event_manager", "get_alarms"),
    "unifi_recent_events": ("event_manager", "get_recent_from_buffer"),
    "unifi_get_event_types": ("event_manager", "get_event_type_prefixes"),
    "unifi_archive_alarm": ("event_manager", "archive_alarm"),
    "unifi_archive_all_alarms": ("event_manager", "archive_all_alarms"),
    # =========================================================================
    # Protect — preview/execute split (preview_X + X, X + apply_X patterns)
    # =========================================================================
    "protect_alarm_arm": ("alarm_manager", "arm"),
    "protect_alarm_disarm": ("alarm_manager", "disarm"),
    # Alarm rule CRUD uses the facade so v2 UUID rules and legacy ObjectID rules
    # route through the same family-aware path as the Protect MCP tools.
    "protect_alarm_update_rule": ("alarm_facade", "update_rule"),
    "protect_alarm_delete_rule": ("alarm_facade", "delete_rule"),
    "protect_ptz_move": ("camera_manager", "ptz_move"),
    "protect_ptz_preset": ("camera_manager", "ptz_goto_preset"),
    "protect_ptz_zoom": ("camera_manager", "ptz_zoom"),
    "protect_reboot_camera": ("camera_manager", "apply_reboot_camera"),
    "protect_toggle_recording": ("camera_manager", "apply_toggle_recording"),
    "protect_toggle_rtsp": ("camera_manager", "apply_toggle_rtsp"),
    "protect_update_camera_settings": ("camera_manager", "update_camera_settings"),
    "protect_update_sensor_settings": ("sensor_manager", "apply_sensor_settings"),
    "protect_update_chime": ("chime_manager", "apply_chime_settings"),
    "protect_update_light": ("light_manager", "apply_light_settings"),
    "protect_update_viewer": ("system_manager", "apply_viewer_update"),
    "protect_acknowledge_event": ("event_manager", "apply_acknowledge_event"),
    "protect_update_known_face": ("recognition_manager", "apply_update_known_face"),
    "protect_merge_known_faces": ("recognition_manager", "apply_merge_known_faces"),
    "protect_delete_known_face": ("recognition_manager", "apply_delete_known_face"),
    "protect_update_known_license_plate": ("recognition_manager", "apply_update_known_license_plate"),
    "protect_delete_known_license_plate": ("recognition_manager", "apply_delete_known_license_plate"),
    # =========================================================================
    # Access — preview/execute split (X + apply_X)
    # =========================================================================
    "access_create_credential": ("credential_manager", "apply_create_credential"),
    "access_revoke_credential": ("credential_manager", "apply_revoke_credential"),
    "access_reboot_device": ("device_manager", "apply_reboot_device"),
    "access_update_device_config": ("device_manager", "apply_update_device_config"),
    "access_lock_door": ("door_manager", "apply_lock_door"),
    "access_unlock_door": ("door_manager", "apply_unlock_door"),
    "access_update_policy": ("policy_manager", "apply_update_policy"),
    "access_create_visitor": ("visitor_manager", "apply_create_visitor"),
    "access_delete_visitor": ("visitor_manager", "apply_delete_visitor"),
}


@dataclass(frozen=True)
class DispatchBindingOverride:
    """Build-time manager binding that explains why AST discovery is insufficient."""

    manager_attr: str
    manager_method: str
    reason: str


@dataclass(frozen=True)
class ActionExclusion:
    """An MCP-only tool deliberately omitted from request/response actions."""

    product: str
    reason: str


_NON_EVENT_OVERRIDE_REASON = (
    "the tool wrapper previews, branches, or reshapes arguments before the Core call; "
    "REST dispatch must bind directly to the authoritative manager method"
)
_EVENT_OVERRIDE_REASON = "the tool resolves EventManager through a lazy helper, so no runtime singleton call exists"
_EVENT_OVERRIDE_NAMES = frozenset(
    {
        "unifi_list_events",
        "unifi_list_alarms",
        "unifi_recent_events",
        "unifi_get_event_types",
        "unifi_archive_alarm",
        "unifi_archive_all_alarms",
    }
)

DISPATCH_BINDING_OVERRIDES: dict[str, DispatchBindingOverride] = {
    name: DispatchBindingOverride(
        manager_attr=manager_attr,
        manager_method=manager_method,
        reason=_EVENT_OVERRIDE_REASON if name in _EVENT_OVERRIDE_NAMES else _NON_EVENT_OVERRIDE_REASON,
    )
    for name, (manager_attr, manager_method) in DISPATCH_OVERRIDES.items()
}

_MCP_SUBSCRIPTION_EXCLUSION_REASON = (
    "returns MCP resource and polling instructions; API SSE and event resources are the authoritative streaming surface"
)
API_ACTION_EXCLUSIONS: dict[str, ActionExclusion] = {
    "access_subscribe_events": ActionExclusion("access", _MCP_SUBSCRIPTION_EXCLUSION_REASON),
    "protect_subscribe_events": ActionExclusion("protect", _MCP_SUBSCRIPTION_EXCLUSION_REASON),
    "unifi_subscribe_events": ActionExclusion("network", _MCP_SUBSCRIPTION_EXCLUSION_REASON),
}

# Format: tool_name -> callable(args_dict) -> (positional_args, keyword_args)
#
# The default dispatcher invokes ``manager.method(**args)``. Tools registered
# here override that with a translator that returns the exact positional and
# keyword arguments the manager method accepts. Use this when the MCP tool
# layer does meaningful shape translation (e.g., flat kwargs -> controller-
# nested payload) that the dispatcher would otherwise skip.
ArgTranslator = Callable[[dict[str, Any]], tuple[tuple[Any, ...], dict[str, Any]]]


@dataclass(frozen=True)
class ArgTranslatorSpec:
    """Callable argument adapter with a machine-checkable manager contract."""

    translate: ArgTranslator
    manager_parameters: frozenset[str]

    def __call__(self, args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return self.translate(args)


def _spec(translate: ArgTranslator, *manager_parameters: str) -> ArgTranslatorSpec:
    return ArgTranslatorSpec(translate, frozenset(manager_parameters))


def _rename_and_drop(
    *,
    rename: dict[str, str] | None = None,
    drop: frozenset[str] = frozenset(),
    constants: dict[str, Any] | None = None,
) -> ArgTranslator:
    """Build a simple keyword adapter without silently retaining tool-only args."""

    def translate(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        out = {key: value for key, value in args.items() if key not in drop}
        for source, target in (rename or {}).items():
            if source in out:
                out[target] = out.pop(source)
        out.update(constants or {})
        return (), out

    return translate


def _translate_firewall_zone_crud(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Normalize zone identifiers and names before preview or confirmed dispatch."""
    out = {key: value for key, value in args.items() if key != "confirm"}
    for key in ("zone_id", "name"):
        value = out.get(key)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError(f"{key} is required")
            out[key] = value
    return (), out


def _pack_fields(
    target: str,
    fields: frozenset[str],
    *,
    passthrough: frozenset[str] = frozenset(),
    field_renames: dict[str, str] | None = None,
) -> ArgTranslator:
    """Pack flat tool fields into one manager payload argument."""

    def translate(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        payload = {
            (field_renames or {}).get(key, key): value
            for key, value in args.items()
            if key in fields and value is not None
        }
        out = {key: args[key] for key in passthrough if key in args}
        out[target] = payload
        return (), out

    return translate


def _rename_payload(source: str, target: str, *, passthrough: frozenset[str] = frozenset()) -> ArgTranslator:
    """Rename one nested payload while retaining explicitly named identifiers."""

    def translate(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        out = {key: args[key] for key in passthrough if key in args}
        out[target] = args.get(source) or {}
        return (), out

    return translate


def _translate_acl_create(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Build the controller-shaped payload AclManager.create_acl_rule expects.

    Mirrors the translation in
    ``apps/network/src/unifi_network_mcp/tools/acl.py:create_acl_rule``.
    """
    from pydantic import ValidationError
    from unifi_core.network.models.acl import build_acl_rule, to_controller_create

    try:
        rule = build_acl_rule(args)
    except ValidationError as e:
        # Surface the same clean message the MCP tool returns, not a raw pydantic dump.
        msg = e.errors()[0].get("msg", str(e)) if e.errors() else str(e)
        raise ValueError(f"Invalid ACL rule: {msg}") from e
    return (to_controller_create(rule),), {}


def _translate_acl_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Build (rule_id, controller_update_payload) for AclManager.update_acl_rule.

    Mirrors the translation in
    ``apps/network/src/unifi_network_mcp/tools/acl.py:update_acl_rule``.
    Only fields the caller actually supplied are passed through.
    """
    from unifi_core.network.models.acl import (
        CLEAR_NETMASK_FIELDS,
        MUTABLE_FIELDS,
        to_controller_update,
        validate_update_fields,
    )

    rule_id = args["rule_id"]
    # The mutable fields are nested in the rule_data dict (the tool's signature is
    # update_acl_rule(rule_id, rule_data: dict, clear_*, confirm)) — NOT top-level args.
    rule_data = args.get("rule_data") or {}
    unknown_fields = set(rule_data) - MUTABLE_FIELDS
    if unknown_fields:
        raise ValueError(
            f"Unknown or read-only fields: {sorted(unknown_fields)}. Allowed fields: {sorted(MUTABLE_FIELDS)}"
        )
    ok, err = validate_update_fields(rule_data)
    if not ok:
        raise ValueError(err)
    fields = dict(rule_data)
    # The clear-netmask sentinels are TOP-LEVEL args (siblings of rule_data), not members
    # of rule_data / MUTABLE_FIELDS.
    has_clear = False
    for clear_key in CLEAR_NETMASK_FIELDS:
        if args.get(clear_key):
            fields[clear_key] = True
            has_clear = True
    # Parity with the MCP tool: reject a no-op update (no fields and no clear).
    if not fields and not has_clear:
        raise ValueError("No fields to update")
    return (rule_id, to_controller_update(fields)), {}


def _translate_gateway_settings_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Filter the gateway-settings update payload to mutable keys before dispatch.

    Mirrors the ``gw_to_update`` filter the MCP tool applies
    (``apps/network/src/unifi_network_mcp/tools/gateway_settings.py``) so the
    ``/v1/actions`` path does not forward read-only / unknown keys into the
    fetch-merge-put. The manager method is ``update_gateway_settings(update_data)``.
    """
    from unifi_core.network.models.gateway_settings import to_controller_update

    update_data = args.get("update_data") or {}
    if not update_data:
        raise ValueError("update_data cannot be empty")
    payload = to_controller_update(update_data)
    if not payload:
        raise ValueError("No valid mutable fields provided for update")
    return (payload,), {}


def _translate_create_dynamic_dns(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Validate + translate ``entry_data`` → controller create payload for
    ``DynamicDnsManager.create_dynamic_dns(entry_data)``.

    Mirrors ``apps/network/src/unifi_network_mcp/tools/dynamic_dns.py:create_dynamic_dns``:
    reject unknown / read-only keys (so they are not forwarded raw to the
    controller) and require ``host_name`` + ``service``.
    """
    from unifi_core.network.models.dynamic_dns import (
        MUTABLE_FIELDS,
        DynamicDns,
        reject_unknown_fields,
        to_controller_create,
    )

    entry_data = args.get("entry_data") or {}
    reject_unknown_fields(entry_data)
    model = DynamicDns(**{k: v for k, v in entry_data.items() if k in MUTABLE_FIELDS})
    if not model.host_name or not model.service:
        raise ValueError("'host_name' and 'service' are required")
    return (to_controller_create(model),), {}


def _translate_update_dynamic_dns(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Reshape ``(entry_id, update_data)`` → positional ``(entry_id, payload)`` for
    ``DynamicDnsManager.update_dynamic_dns(entry_id, entry_data)``.

    The tool exposes ``update_data`` but the manager parameter is ``entry_data``,
    so the default ``method(**args)`` would pass an unexpected ``update_data=``
    kwarg. Mirrors the MCP tool: reject unknown / read-only keys, then filter to
    mutable fields.
    """
    from unifi_core.network.models.dynamic_dns import reject_unknown_fields, to_controller_update

    entry_id = args["entry_id"]
    update_data = args.get("update_data") or {}
    if not update_data:
        raise ValueError("No fields provided to update.")
    reject_unknown_fields(update_data)
    validated = to_controller_update(update_data)
    if not validated:
        raise ValueError("No valid fields to update after validation.")
    return (entry_id, validated), {}


def _parse_iso_datetime(value: Any) -> Any:
    """Parse an ISO 8601 string into a datetime; pass through datetime values."""
    from datetime import datetime

    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    raise ValueError(f"cannot parse datetime from {type(value).__name__}: {value!r}")


def _translate_export_clip(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Parse ISO start/end strings into datetime for recording_manager.export_clip."""
    from unifi_core.protect.models._actions import ExportClipInput

    model = ExportClipInput(**args)
    public = model.model_dump(exclude_none=True)
    kwargs: dict[str, Any] = {
        "camera_id": public["camera_id"],
        "start": _parse_iso_datetime(public["start"]),
        "end": _parse_iso_datetime(public["end"]),
    }
    if "channel_index" in public:
        kwargs["channel_index"] = public["channel_index"]
    if "fps" in public:
        kwargs["fps"] = public["fps"]
    return (), kwargs


def _translate_detection_search(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    out = dict(args)
    out.setdefault("limit", 100)
    out.setdefault("order", "desc")
    out.setdefault("exclude_motion", True)
    out.setdefault("min_confidence", None)
    out["start"] = _parse_iso_datetime(out.get("start"))
    out["end"] = _parse_iso_datetime(out.get("end"))
    return (), out


def _translate_ptz_preset(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.protect.models._actions import PtzPresetInput

    return (), PtzPresetInput(**args).model_dump()


def _translate_ptz_move(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.protect.models._actions import PtzMoveInput

    return (), PtzMoveInput(**args).model_dump()


def _translate_toggle_rtsp(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.protect.models._actions import ToggleRtspInput

    return (), ToggleRtspInput(**args).model_dump()


def _translate_trigger_chime(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.protect.models._actions import TriggerChimeInput

    return (), TriggerChimeInput(**args).model_dump(exclude_none=True)


def _translate_alarm_create(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.protect.models._actions import AlarmCreateRuleInput
    from unifi_core.protect.models._validators import require_non_empty_actions

    fields = dict(AlarmCreateRuleInput(body=args["body"]).body)
    require_non_empty_actions(fields.get("actions"))
    return (), {"fields": fields}


def _translate_alarm_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.protect.models._actions import AlarmUpdateRuleInput
    from unifi_core.protect.models._validators import require_non_empty_actions

    fields = dict(args["fields"])
    if not fields:
        raise ValueError("No fields provided. Specify at least one field to update.")
    validated = AlarmUpdateRuleInput(rule_id=args["rule_id"], body=fields)
    if "actions" in fields:
        require_non_empty_actions(fields["actions"])
    return (), {"rule_id": validated.rule_id, "fields": dict(validated.body)}


def _translate_alarm_delete(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.protect.models._actions import AlarmDeleteRuleInput

    return (), AlarmDeleteRuleInput(**args).model_dump()


def _translate_access_unlock(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.access.models._actions import UnlockDoorInput

    return (), UnlockDoorInput(**args).model_dump()


def _translate_create_voucher(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models._actions import CreateVoucherInput

    return (), CreateVoucherInput(**args).model_dump(exclude_none=True)


def _translate_delete_recording(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Parse ISO start/end strings into datetime for recording_manager.delete_recording."""
    return (), {
        "camera_id": args["camera_id"],
        "start": _parse_iso_datetime(args["start"]),
        "end": _parse_iso_datetime(args["end"]),
    }


def _alarm_facade_result(result: Any, _args: dict[str, Any], _manager: Any) -> dict[str, Any]:
    if not (
        isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], dict) and isinstance(result[1], bool)
    ):
        raise ValueError("Alarm facade returned an invalid mutation result")
    payload, complete = result
    out = dict(payload)
    if not complete:
        out["_meta"] = {
            "com.github.sirkirby.unifi-mcp/alarm-coverage": {
                "complete": False,
                "reason": (
                    "Showing legacy Protect automations: the UniFi-OS Alarm Manager "
                    "(/api/v2/alarms) returned no rules or is unavailable on this console, "
                    "so AI-powered alarms (where supported) are not included."
                ),
            }
        }
    return out


def _delete_recording_result(result: Any, _args: dict[str, Any], _manager: Any) -> Any:
    if isinstance(result, dict) and result.get("supported") is False:
        raise ValueError(str(result.get("message") or "Individual recording deletion is not supported"))
    return result


# ---------------------------------------------------------------------------
# Protect — sensor settings update
# ---------------------------------------------------------------------------
# The MCP tool validates agent-facing settings and translates nested
# snake_case keys to the public API payload before calling the manager.


def _translate_sensor_settings_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Build (sensor_id, public_update_payload) for SensorManager.apply_sensor_settings."""
    from unifi_core.protect.models.sensors import to_public_update

    return (args["sensor_id"], to_public_update(args.get("settings") or {})), {}


def _translate_chime_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Build (chime_id, filtered_settings) for ChimeManager.apply_chime_settings."""
    from unifi_core.protect.models.chimes import to_controller_update, to_ring_setting_update

    settings = args.get("settings")
    if not settings:
        raise ValueError("No settings provided. Specify at least one setting to update.")
    if not isinstance(settings, dict):
        raise ValueError("Chime settings must be a dictionary for protect_update_chime.")

    if "camera_id" in settings:
        filtered = to_ring_setting_update(settings)
    else:
        filtered = to_controller_update(settings)
    if not filtered:
        raise ValueError("No supported settings provided.")
    return (args["chime_id"], filtered), {}


# ---------------------------------------------------------------------------
# Network — client manager tools
# ---------------------------------------------------------------------------
# All eight client mutation tools expose ``mac_address`` to the LLM; every
# manager method takes ``client_mac`` instead.  A single shared helper
# covers the rename; callers that pass additional kwargs (rename, authorize,
# set_client_ip_settings) carry those through unchanged.


def _rename_mac_address_to_client_mac(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Rename ``mac_address`` → ``client_mac`` for client manager methods.

    Shared by all eight client mutation tools whose LLM-facing parameter is
    ``mac_address`` but whose manager method parameter is ``client_mac``.
    All other kwargs are passed through unchanged.
    """
    out = dict(args)
    if "mac_address" in out:
        out["client_mac"] = out.pop("mac_address")
    return (), out


# ---------------------------------------------------------------------------
# Network — list_clients
# ---------------------------------------------------------------------------
# Core owns the online-vs-historical selection; the remaining public options
# are applied by the shared result view after the manager returns.


def _translate_list_clients(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Pass only the Core client-source selector to ``get_clients``."""
    return (), {"include_offline": args.get("include_offline", False)}


# ---------------------------------------------------------------------------
# Network — update_firewall_policy
# ---------------------------------------------------------------------------
# Tool exposes ``update_data``; manager method takes ``updates``.


def _translate_update_firewall_policy(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Validate and normalize a V2 firewall-policy partial update."""
    from unifi_core.network.models.firewall import normalize_policy_update

    return (), {
        "policy_id": args["policy_id"],
        "updates": normalize_policy_update(args.get("update_data") or {}),
    }


# ---------------------------------------------------------------------------
# Network — port forward id rename
# ---------------------------------------------------------------------------
# Port forward tools expose ``port_forward_id``; the firewall_manager methods
# (``toggle_port_forward`` / ``delete_port_forward``) take ``rule_id``. Shared
# by both, mirroring ``_rename_mac_address_to_client_mac``.


def _rename_port_forward_id_to_rule_id(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Rename ``port_forward_id`` → ``rule_id`` for firewall_manager port-forward methods."""
    out = dict(args)
    if "port_forward_id" in out:
        out["rule_id"] = out.pop("port_forward_id")
    return (), out


# ---------------------------------------------------------------------------
# Network — update_device_radio
# ---------------------------------------------------------------------------
# Tool exposes flat radio settings (``mac_address``, ``radio``, individual
# update fields) alongside ``confirm``.  Manager ``update_device_radio``
# expects ``(device_mac, radio_id, updates)`` where ``updates`` is a dict
# of radio-table fields.  The translator renames ``mac_address`` →
# ``device_mac``, ``radio`` → ``radio_id``, and collects the per-field
# kwargs into an ``updates`` dict.

_RADIO_UPDATE_FIELDS = frozenset(
    {
        "tx_power_mode",
        "tx_power",
        "channel",
        "ht",
        "min_rssi_enabled",
        "min_rssi",
        "assisted_roaming_enabled",
        "antenna_gain",
        "vwire_enabled",
        "sens_level_enabled",
        "sens_level",
    }
)


def _translate_update_device_radio(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Translate flat radio kwargs to (device_mac, radio_id, updates) shape.

    The MCP tool accepts individual radio-setting fields alongside
    ``mac_address`` and ``radio``; the manager method takes them bundled
    into an ``updates`` dict.
    """
    out = dict(args)
    device_mac = out.pop("mac_address", None)
    radio_id = out.pop("radio", None)
    # Collect radio-table field kwargs into the updates bundle.
    updates = {k: out.pop(k) for k in list(out.keys()) if k in _RADIO_UPDATE_FIELDS}
    kwargs: dict[str, Any] = {}
    if device_mac is not None:
        kwargs["device_mac"] = device_mac
    if radio_id is not None:
        kwargs["radio_id"] = radio_id
    if updates:
        kwargs["updates"] = updates
    return (), kwargs


# ---------------------------------------------------------------------------
# Network — stats tools
# ---------------------------------------------------------------------------
# ``get_top_clients(duration_hours, limit)`` — tool passes ``duration`` (a
# string like "daily") and ``limit``; manager expects ``duration_hours``
# (an integer).

_DURATION_HOURS: dict[str, int] = {
    "hourly": 1,
    "daily": 24,
    "weekly": 168,
    "monthly": 720,
}


def _translate_get_top_clients(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Convert ``duration`` string → ``duration_hours`` int for stats_manager.get_top_clients."""
    out = dict(args)
    duration = out.pop("duration", "daily")
    duration_hours = _DURATION_HOURS.get(str(duration), 1)
    return (), {"duration_hours": duration_hours, "limit": out.get("limit", 10)}


def _translate_list_events(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Rename the tool's within_hours filter to EventManager's within argument."""
    out = dict(args)
    if "within_hours" in out:
        out["within"] = out.pop("within_hours")
    # The wrapper applies the optional absolute end bound after fetching.
    out.pop("end", None)
    return (), out


def _translate_client_ip_settings(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Rename the MAC and remove the wrapper-only network lookup hint."""
    from unifi_core.network.models._actions import SetClientIpSettingsInput

    model = SetClientIpSettingsInput(**args)
    public = model.model_dump(exclude_none=True)
    client_mac = public.pop("mac_address")
    if not public:
        raise ValueError(
            "At least one setting must be provided "
            "(use_fixedip, fixed_ip, local_dns_record_enabled, or local_dns_record)."
        )
    return (), {"client_mac": client_mac, **public}


def _translate_authorize_guest(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models._actions import AuthorizeGuestInput

    model = AuthorizeGuestInput(**args)
    public = model.model_dump(exclude_none=True)
    public["client_mac"] = public.pop("mac_address")
    return (), public


def _translate_list_alarms(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Rename the tool's include_archived filter to EventManager's archived argument."""
    out = dict(args)
    if "include_archived" in out:
        out["archived"] = out.pop("include_archived")
    return (), out


def _translate_duration(
    args: dict[str, Any],
    *,
    default_hours: int,
    rename: dict[str, str] | None = None,
    drop: frozenset[str] = frozenset(),
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Convert the shared duration enum and apply any identifier renames."""
    out = {key: value for key, value in args.items() if key not in drop}
    duration = out.pop("duration", None)
    if duration is not None:
        out["duration_hours"] = _DURATION_HOURS.get(str(duration), default_hours)
    for source, target in (rename or {}).items():
        if source in out:
            out[target] = out.pop(source)
    return (), out


def _translate_traffic_flows(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Build the Core TrafficFlowQuery used by the MCP wrapper."""
    import time

    from unifi_core.network.models.traffic_flows import TrafficFlowQuery

    def as_list(value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]

    time_from = args.get("time_from")
    time_to = args.get("time_to")
    if (time_from is None) != (time_to is None):
        raise ValueError("provide both time_from and time_to, or use within_hours")
    if time_from is None:
        within_hours = int(args.get("within_hours", 24))
        if within_hours <= 0:
            raise ValueError("within_hours must be a positive integer")
        time_to = int(time.time() * 1000)
        time_from = time_to - within_hours * 3_600_000

    query = TrafficFlowQuery(
        time_from=time_from,
        time_to=time_to,
        page_number=args.get("page", 0),
        page_size=max(1, min(args.get("page_size", 100), 1000)),
        search_text=args.get("search_text"),
        risk=as_list(args.get("risk")),
        action=as_list(args.get("action")),
        direction=as_list(args.get("direction")),
        protocol=as_list(args.get("protocol")),
        service=as_list(args.get("service")),
        source_mac=as_list(args.get("source_mac")),
        source_ip=as_list(args.get("source_ip")),
        source_host=as_list(args.get("source_name")),
        source_network_id=as_list(args.get("source_network_id")),
        destination_domain=as_list(args.get("destination_domain")),
        destination_ip=as_list(args.get("destination_ip")),
        destination_region=as_list(args.get("destination_region")),
    )
    return (), {"query": query}


def _validated_network_fields(fields: dict[str, Any], *, operation: str) -> dict[str, Any]:
    from unifi_core.network.models.networks import validate_create, validate_update

    return validate_create(fields) if operation == "create" else validate_update(fields)


def _translate_network_create(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    network_data = _validated_network_fields(dict(args.get("network_data") or {}), operation="create")
    return (), {"network_data": network_data}


def _translate_network_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    update_data = _validated_network_fields(dict(args.get("update_data") or {}), operation="update")
    return (), {"network_id": args["network_id"], "update_data": update_data}


def _translate_wlan_create(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.wlans import validate_create

    return (), {"wlan_data": validate_create(dict(args.get("wlan_data") or {}))}


def _translate_wlan_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.wlans import validate_update

    return (), {"wlan_id": args["wlan_id"], "update_data": validate_update(dict(args.get("update_data") or {}))}


def _translate_snmp_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.system import snmp_to_controller_update

    updates = {"enabled": args["enabled"]}
    if args.get("community") is not None:
        updates["community"] = args["community"]
    return (), {"section": "snmp", "settings_data": snmp_to_controller_update(updates)}


def _translate_switch_stp(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    return (), {
        "device_mac": args["device_mac"],
        "config_data": {
            "stp_priority": str(args.get("stp_priority", 32768)),
            "stp_version": args.get("stp_version", "rstp"),
        },
    }


def _translate_jumbo_frames(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    return (), {
        "device_mac": args["device_mac"],
        "config_data": {"jumboframe_enabled": args["enabled"]},
    }


def _translate_route_args(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.route import validate_static_route_fields

    out = dict(args)
    route_id = out.pop("route_id", None)
    out = validate_static_route_fields(out, require_complete=route_id is None)
    if route_id is not None:
        out["route_id"] = route_id
    for source, target in {
        "network": "static_route_network",
        "nexthop": "static_route_nexthop",
        "distance": "static_route_distance",
    }.items():
        if source in out:
            out[target] = out.pop(source)
    return (), out


def _translate_update_port_forward(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models._actions import PortForwardUpdateInput
    from unifi_core.network.models.port_forwards import to_controller_update

    model = PortForwardUpdateInput(**(args.get("update_data") or {}))
    public = model.model_dump(exclude_none=True)
    if "protocol" in public:
        public["fwd_protocol"] = public.pop("protocol")
    if "src_ip" in public:
        public["src"] = public.pop("src_ip") or None
    updates = to_controller_update(public)
    if not updates:
        raise ValueError("No valid mutable fields provided for port-forward update")
    return (), {"rule_id": args["port_forward_id"], "updates": updates}


def _translate_snapshot(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    out = dict(args)
    out.pop("include_image", None)
    return (), out


def _translate_recent_events(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    out = dict(args)
    out.pop("metadata_fields", None)
    return (), out


def _translate_create_client_group(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    return (), {
        "group_data": {
            "name": args["name"],
            "members": args["members"],
            "type": "CLIENTS",
        }
    }


def _port_forward_payload(model: Any) -> dict[str, Any]:
    from unifi_core.network.models.port_forwards import PortForward, to_controller_create

    rule = PortForward(
        name=model.name,
        dst_port=model.dst_port,
        fwd_port=model.fwd_port,
        fwd_ip=model.fwd_ip,
        fwd_protocol=model.protocol,
        enabled=model.enabled,
        src=model.src_ip or None,
        log=model.log,
    )
    payload = to_controller_create(rule)
    payload["protocol_match_excepted"] = False
    return payload


def _translate_create_port_forward(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models._actions import PortForwardCreateInput

    model = PortForwardCreateInput(**(args.get("port_forward_data") or {}))
    return (), {"rule_data": _port_forward_payload(model)}


def _translate_create_simple_port_forward(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models._actions import PortForwardCreateInput, PortForwardSimpleInput

    simple = PortForwardSimpleInput(**(args.get("rule") or {}))
    model = PortForwardCreateInput(
        name=simple.name,
        dst_port=simple.ext_port,
        fwd_port=simple.int_port if simple.int_port is not None else simple.ext_port,
        fwd_ip=simple.to_ip,
        protocol={"tcp": "tcp", "udp": "udp", "both": "tcp_udp"}.get(simple.protocol, "tcp_udp"),
        enabled=simple.enabled,
    )
    return (), {"rule_data": _port_forward_payload(model)}


def _translate_create_qos_rule(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.qos import to_controller_update

    rule_data = to_controller_update(args.get("qos_data") or {})
    missing = [key for key in ("name", "interface", "direction", "bandwidth_limit_kbps") if key not in rule_data]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")
    rule_data.setdefault("enabled", True)
    return (), {"rule_data": rule_data}


def _translate_create_simple_qos_rule(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models._actions import QosRuleSimpleInput

    rule = QosRuleSimpleInput(**(args.get("rule") or {}))
    payload: dict[str, Any] = {
        "name": rule.name,
        "interface": rule.interface,
        "direction": rule.direction,
        "bandwidth_limit_kbps": rule.limit_kbps,
        "enabled": rule.enabled,
    }
    if rule.dscp_value is not None:
        payload["dscp_value"] = rule.dscp_value
    if rule.target is not None:
        target_type = rule.target.type.lower()
        if target_type == "ip":
            payload["target_ip_address"] = rule.target.value
        elif target_type == "subnet":
            payload["target_subnet"] = rule.target.value
        else:
            raise ValueError(f"Unsupported target type '{target_type}'")
    return (), {"rule_data": payload}


def _translate_create_oon_policy(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.oon import OonPolicy, to_controller_create

    target_type = str(args["target_type"]).upper()
    if target_type not in {"CLIENTS", "GROUPS"}:
        raise ValueError(f"target_type must be 'CLIENTS' or 'GROUPS', got '{args['target_type']}'")
    if not args.get("targets"):
        raise ValueError("targets must be a non-empty list")
    if not any(args.get(key) is not None for key in ("secure", "qos", "route")):
        raise ValueError("At least one of secure, qos, or route must be provided")
    model = OonPolicy(
        name=args["name"],
        enabled=args.get("enabled", True),
        target_type=target_type,
        targets=args["targets"],
        secure=args.get("secure"),
        qos=args.get("qos"),
        route=args.get("route"),
    )
    return (), {"policy_data": to_controller_create(model)}


def _translate_model_update(
    args: dict[str, Any],
    *,
    id_source: str,
    id_target: str,
    payload_source: str,
    payload_target: str,
    converter: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    payload = converter(args.get(payload_source) or {})
    if not payload:
        raise ValueError(f"No valid mutable fields provided for {payload_source}")
    return (), {id_target: args[id_source], payload_target: payload}


def _translate_content_filter_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.content_filter import to_controller_update

    return _translate_model_update(
        args,
        id_source="filter_id",
        id_target="filter_id",
        payload_source="filter_data",
        payload_target="update_data",
        converter=to_controller_update,
    )


def _translate_client_group_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.client_group import to_controller_update

    return _translate_model_update(
        args,
        id_source="group_id",
        id_target="group_id",
        payload_source="group_data",
        payload_target="update_data",
        converter=to_controller_update,
    )


def _translate_dns_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.dns import to_controller_update

    return _translate_model_update(
        args,
        id_source="record_id",
        id_target="record_id",
        payload_source="update_data",
        payload_target="record_data",
        converter=to_controller_update,
    )


def _translate_oon_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.oon import to_controller_update

    return _translate_model_update(
        args,
        id_source="policy_id",
        id_target="policy_id",
        payload_source="policy_data",
        payload_target="update_data",
        converter=to_controller_update,
    )


def _translate_port_profile_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.switch import to_controller_update

    return _translate_model_update(
        args,
        id_source="profile_id",
        id_target="profile_id",
        payload_source="profile_data",
        payload_target="update_data",
        converter=to_controller_update,
    )


def _translate_port_profile_create(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Build the port-profile create payload the way the MCP tool does.

    Packing only the supplied keys is not equivalent here: ``poe_mode``,
    ``stp_port_mode`` and ``isolation`` must be sent even when the caller takes
    the documented default, or the controller applies its own — for ``poe_mode``
    that means the profile is created with PoE off. Shares
    ``build_create_payload`` with
    ``apps/network/src/unifi_network_mcp/tools/switch.py:create_port_profile``.
    """
    from unifi_core.network.models.switch import build_create_payload

    accepted = {
        "name",
        "forward",
        "native_networkconf_id",
        "tagged_vlan_mgmt",
        "tagged_networkconf_ids",
        "excluded_networkconf_ids",
        "voice_networkconf_id",
        "isolation",
        "poe_mode",
        "stp_port_mode",
        "stp_edge_state",
        "stp_bpdu_guard_enabled",
        "stp_uplink",
        "dot1x_ctrl",
        "stormctrl_bcast_enabled",
        "stormctrl_bcast_rate",
        "stormctrl_mcast_enabled",
        "stormctrl_mcast_rate",
        "stormctrl_ucast_enabled",
        "stormctrl_ucast_rate",
    }
    supplied = {key: value for key, value in args.items() if key in accepted and value is not None}
    if not supplied.get("name") or not supplied.get("forward"):
        raise ValueError("name and forward are required to create a port profile.")
    return (), {"profile_data": build_create_payload(**supplied)}


def _translate_autobackup_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.system import autobackup_to_controller_update

    settings = autobackup_to_controller_update(args.get("update_data") or {})
    if not settings:
        raise ValueError("No valid auto-backup settings provided")
    return (), {"settings": settings}


def _translate_access_credential(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.access.models.credentials import Credential, to_controller_create

    data = args.get("credential_data") or {}
    if not data:
        raise ValueError("No credential data provided")
    model = Credential(
        type=args["credential_type"],
        user_id=data.get("user_id"),
        token=data.get("token"),
        pin_code=data.get("pin_code"),
    )
    payload = to_controller_create(model)
    return (), payload


def _translate_radio_update(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    from unifi_core.network.models.devices import validate_radio_update

    out = dict(args)
    device_mac = out.pop("mac_address")
    radio_id = out.pop("radio")
    updates = validate_radio_update(
        radio_id,
        {key: value for key, value in out.items() if key in _RADIO_UPDATE_FIELDS},
    )
    return (), {"device_mac": device_mac, "radio_id": radio_id, "updates": updates}


def _translate_device_led(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    led_state = args["led_state"]
    valid_states = ("on", "off", "default")
    if led_state not in valid_states:
        raise ValueError(f"Invalid led_state '{led_state}'. Must be one of: {', '.join(valid_states)}")
    return (), {"device_mac": args["device_mac"], "led_override": led_state}


def _snapshot_direct_result(args: dict[str, Any]) -> tuple[bool, Any]:
    if args.get("include_image", False):
        return False, None
    camera_id = args["camera_id"]
    return True, {"snapshot_url": f"protect://cameras/{camera_id}/snapshot"}


def _snapshot_result(result: Any, _args: dict[str, Any], _manager: Any) -> dict[str, Any]:
    if not isinstance(result, (bytes, bytearray)):
        raise ValueError("Protect snapshot manager returned a non-bytes result")
    return {
        "image_base64": base64.b64encode(result).decode(),
        "content_type": "image/jpeg",
    }


def _recent_events_result(result: Any, args: dict[str, Any], manager: Any) -> dict[str, Any]:
    from unifi_core.protect.models.events import from_controller as event_from_controller

    metadata_fields = args.get("metadata_fields") or None
    processed: list[dict[str, Any]] = []
    for raw in result:
        event = dict(raw)
        event.pop("_buffered_at", None)
        if metadata_fields is None:
            event.pop("metadata", None)
        elif "*" not in metadata_fields:
            metadata = event.get("metadata") or {}
            event["metadata"] = {key: metadata[key] for key in metadata_fields if key in metadata}
            if not event["metadata"]:
                event.pop("metadata", None)
        processed.append(event_from_controller(event).model_dump(exclude_none=True))
    return {
        "events": processed,
        "count": len(processed),
        "source": "websocket_buffer",
        "buffer_size": manager.buffer_size,
    }


def _manager_site(manager: Any) -> str:
    return str(manager._connection.site)


def _list_clients_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    payload = shape_client_list(
        result,
        site=_manager_site(manager),
        filter_type=args.get("filter_type", "all"),
        search=args.get("search"),
        limit=args.get("limit", 100),
        fields=args.get("fields"),
    )
    return ShapedReadResult(
        payload,
        "clients",
        {
            "primary_key": "mac",
            "display_columns": ["name", "ip", "connection_type", "status"],
            "sort_default": "name:asc",
        },
    )


def _alerts_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    payload = shape_alerts(
        result,
        site=_manager_site(manager),
        limit=args.get("limit", 10),
        include_archived=args.get("include_archived", False),
    )
    return ShapedReadResult(
        payload,
        "alerts",
        {
            "primary_key": "_id",
            "display_columns": ["timestamp", "key", "msg", "mac"],
            "sort_default": "timestamp:desc",
        },
    )


def _client_details_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    payload = shape_client_details(
        result,
        site=_manager_site(manager),
        mac_address=args["mac_address"],
        include=args.get("include", "basic"),
        summary=args.get("summary", False),
    )
    return ShapedReadResult(payload, "client")


def _dashboard_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    payload = shape_dashboard(
        result,
        site=_manager_site(manager),
        summary=args.get("summary", True),
        history_seconds=args.get("history_seconds", 86400),
    )
    return ShapedReadResult(payload, "dashboard", {"sort_default": "time:desc"})


def _device_details_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    payload = shape_device_details(
        result,
        site=_manager_site(manager),
        mac_address=args["mac_address"],
        include=args.get("include", "basic,ports"),
        summary=args.get("summary", False),
    )
    return ShapedReadResult(payload, "device")


def _network_details_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    payload = shape_network_details(
        result,
        site=_manager_site(manager),
        network_id=args["network_id"],
        include=args.get("include", "basic"),
        summary=args.get("summary", False),
    )
    return ShapedReadResult(payload, "details")


def _list_devices_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    payload = shape_device_list(
        result,
        site=_manager_site(manager),
        device_type=args.get("device_type", "all"),
        status=args.get("status", "all"),
        search=args.get("search"),
        limit=args.get("limit"),
        include_details=args.get("include_details", False),
        summary=args.get("summary", True),
    )
    return ShapedReadResult(
        payload,
        "devices",
        {
            "primary_key": "mac",
            "display_columns": ["name", "model", "type", "status", "ip"],
            "sort_default": "name:asc",
        },
    )


def _firewall_policies_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    summary = args.get("summary", True)
    payload = shape_firewall_policy_list(
        result,
        site=_manager_site(manager),
        search=args.get("search"),
        action=args.get("action"),
        enabled_only=args.get("enabled_only", False),
        limit=args.get("limit", 50),
        summary=summary,
    )
    index_field = "rule_index" if summary else "index"
    return ShapedReadResult(
        payload,
        "policies",
        {
            "primary_key": "id",
            "display_columns": ["name", "action", "enabled", index_field],
            "sort_default": f"{index_field}:asc",
        },
    )


def _list_networks_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    payload = shape_network_list(
        result,
        site=_manager_site(manager),
        search=args.get("search"),
        purpose=args.get("purpose"),
        limit=args.get("limit", 25),
        fields=args.get("fields"),
    )
    return ShapedReadResult(
        payload,
        "networks",
        {
            "primary_key": "_id",
            "display_columns": ["name", "purpose", "vlan", "ip_subnet", "enabled"],
            "sort_default": "name:asc",
        },
    )


def _rogue_aps_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    summary = args.get("summary", True)
    payload = shape_rogue_ap_list(
        result,
        site=_manager_site(manager),
        within_hours=args.get("within_hours", 24),
        channel=args.get("channel"),
        min_signal=args.get("min_signal"),
        limit=args.get("limit", 100),
        offset=args.get("offset", 0),
        summary=summary,
    )
    ssid_field = "ssid" if summary else "essid"
    return ShapedReadResult(
        payload,
        "rogue_aps",
        {
            "primary_key": "bssid",
            "display_columns": ["bssid", ssid_field, "channel", "signal", "last_seen"],
            "sort_default": "signal:desc",
        },
    )


def _wlans_result(result: Any, args: dict[str, Any], manager: Any) -> ShapedReadResult:
    payload = shape_wlan_list(
        result,
        site=_manager_site(manager),
        search=args.get("search"),
        enabled_only=args.get("enabled_only", False),
        limit=args.get("limit", 25),
    )
    return ShapedReadResult(
        payload,
        "wlans",
        {
            "primary_key": "id",
            "display_columns": ["name", "security", "enabled", "network_id"],
            "sort_default": "name:asc",
        },
    )


UNSUPPORTED_ACTION_PARAMETERS: dict[str, frozenset[str]] = {}

DirectResultAdapter = Callable[[dict[str, Any]], tuple[bool, Any]]
ResultAdapter = Callable[[Any, dict[str, Any], Any], Any]

DISPATCH_DIRECT_RESULT_ADAPTERS: dict[str, DirectResultAdapter] = {
    "protect_get_snapshot": _snapshot_direct_result,
}

DISPATCH_RESULT_ADAPTERS: dict[str, ResultAdapter] = {
    "protect_get_snapshot": _snapshot_result,
    "protect_recent_events": _recent_events_result,
    "protect_alarm_create_rule": _alarm_facade_result,
    "protect_alarm_update_rule": _alarm_facade_result,
    "protect_alarm_delete_rule": _alarm_facade_result,
    "protect_delete_recording": _delete_recording_result,
    "unifi_list_clients": _list_clients_result,
    "unifi_get_alerts": _alerts_result,
    "unifi_get_client_details": _client_details_result,
    "unifi_get_dashboard": _dashboard_result,
    "unifi_get_device_details": _device_details_result,
    "unifi_get_network_details": _network_details_result,
    "unifi_list_devices": _list_devices_result,
    "unifi_list_firewall_policies": _firewall_policies_result,
    "unifi_list_networks": _list_networks_result,
    "unifi_list_rogue_aps": _rogue_aps_result,
    "unifi_list_wlans": _wlans_result,
}


def _translate_access_users(args: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    out = dict(args)
    limit = out.pop("limit", None)
    out["page_size"] = limit if isinstance(limit, int) and limit > 0 else 25
    return (), out


DISPATCH_ARG_TRANSLATORS: dict[str, ArgTranslatorSpec] = {
    "unifi_create_acl_rule": _spec(_translate_acl_create, "rule_data"),
    "unifi_update_acl_rule": _spec(_translate_acl_update, "rule_id", "update_data"),
    "unifi_update_gateway_settings": _spec(_translate_gateway_settings_update, "update_data"),
    # Network — dynamic DNS: create validates+translates entry_data; update reshapes
    # (entry_id, update_data) → (entry_id, entry_data) and rejects unknown/read-only keys.
    "unifi_create_dynamic_dns": _spec(_translate_create_dynamic_dns, "entry_data"),
    "unifi_update_dynamic_dns": _spec(_translate_update_dynamic_dns, "entry_id", "entry_data"),
    "protect_export_clip": _spec(_translate_export_clip, "camera_id", "start", "end", "channel_index", "fps"),
    "protect_search_detections": _spec(
        _translate_detection_search,
        "labels",
        "limit",
        "order",
        "exclude_motion",
        "min_confidence",
        "start",
        "end",
    ),
    "protect_ptz_preset": _spec(_translate_ptz_preset, "camera_id", "preset_slot"),
    "protect_ptz_move": _spec(_translate_ptz_move, "camera_id", "pan", "tilt", "duration_ms"),
    "protect_toggle_rtsp": _spec(_translate_toggle_rtsp, "camera_id", "enabled", "quality"),
    "protect_trigger_chime": _spec(_translate_trigger_chime, "chime_id", "volume", "repeat_times"),
    "access_unlock_door": _spec(_translate_access_unlock, "door_id", "duration"),
    "protect_delete_recording": _spec(_translate_delete_recording, "camera_id", "start", "end"),
    "protect_update_chime": _spec(_translate_chime_update, "chime_id", "settings"),
    "protect_update_sensor_settings": _spec(_translate_sensor_settings_update, "sensor_id", "settings"),
    # Network — client mutations: tool uses mac_address, manager uses client_mac
    "unifi_block_client": _spec(_rename_mac_address_to_client_mac, "client_mac"),
    "unifi_unblock_client": _spec(_rename_mac_address_to_client_mac, "client_mac"),
    "unifi_rename_client": _spec(_rename_mac_address_to_client_mac, "client_mac", "name"),
    "unifi_force_reconnect_client": _spec(_rename_mac_address_to_client_mac, "client_mac"),
    "unifi_authorize_guest": _spec(
        _translate_authorize_guest,
        "client_mac",
        "minutes",
        "up_kbps",
        "down_kbps",
        "bytes_quota",
    ),
    "unifi_create_voucher": _spec(
        _translate_create_voucher,
        "expire_minutes",
        "count",
        "quota",
        "note",
        "up_limit_kbps",
        "down_limit_kbps",
        "bytes_limit_mb",
    ),
    "unifi_unauthorize_guest": _spec(_rename_mac_address_to_client_mac, "client_mac"),
    "unifi_set_client_ip_settings": _spec(
        _translate_client_ip_settings,
        "client_mac",
        "use_fixedip",
        "fixed_ip",
        "local_dns_record_enabled",
        "local_dns_record",
    ),
    "unifi_forget_client": _spec(_rename_mac_address_to_client_mac, "client_mac"),
    # Network — list clients: Core selects online or all/historical clients.
    "unifi_list_clients": _spec(_translate_list_clients, "include_offline"),
    # Network — firewall: kwarg rename
    "unifi_update_firewall_policy": _spec(_translate_update_firewall_policy, "policy_id", "updates"),
    # Network — port forward toggle/delete: kwarg rename (port_forward_id → rule_id)
    "unifi_toggle_port_forward": _spec(_rename_port_forward_id_to_rule_id, "rule_id"),
    "unifi_delete_port_forward": _spec(_rename_port_forward_id_to_rule_id, "rule_id"),
    # Network — device radio update: flatten → (device_mac, radio_id, updates)
    "unifi_update_device_radio": _spec(_translate_radio_update, "device_mac", "radio_id", "updates"),
    # Network — stats: convert duration string to duration_hours integer
    "unifi_get_top_clients": _spec(_translate_get_top_clients, "duration_hours", "limit"),
    # Network — event tool names differ from the Core manager signatures.
    "unifi_list_events": _spec(
        _translate_list_events, "event_type", "within", "limit", "start", "categories", "severities"
    ),
    "unifi_list_alarms": _spec(_translate_list_alarms, "archived"),
    # Access public names and pagination aliases.
    "access_create_credential": _spec(_translate_access_credential, "credential_type", "data"),
    "access_list_users": _spec(_translate_access_users, "page_num", "page_size", "compact"),
    # Protect wrapper-only aliases and response-shaping switches.
    "protect_alarm_create_rule": _spec(_translate_alarm_create, "fields"),
    "protect_alarm_update_rule": _spec(_translate_alarm_update, "rule_id", "fields"),
    "protect_alarm_delete_rule": _spec(_translate_alarm_delete, "rule_id"),
    "protect_get_snapshot": _spec(_translate_snapshot, "camera_id", "width", "height"),
    "protect_recent_events": _spec(_translate_recent_events, "event_type", "camera_id", "min_confidence", "limit"),
    # Network identifier aliases.
    "unifi_adopt_device": _spec(_rename_and_drop(rename={"mac_address": "device_mac"}), "device_mac"),
    "unifi_reboot_device": _spec(_rename_and_drop(rename={"mac_address": "device_mac"}), "device_mac"),
    "unifi_rename_device": _spec(_rename_and_drop(rename={"mac_address": "device_mac"}), "device_mac", "name"),
    "unifi_upgrade_device": _spec(_rename_and_drop(rename={"mac_address": "device_mac"}), "device_mac"),
    "unifi_get_device_radio": _spec(_rename_and_drop(rename={"mac_address": "device_mac"}), "device_mac"),
    "unifi_get_pdu_outlets": _spec(_rename_and_drop(rename={"mac_address": "device_mac"}), "device_mac"),
    "unifi_get_port_forward": _spec(_rename_and_drop(rename={"port_forward_id": "rule_id"}), "rule_id"),
    # Network create/update payload packing.
    "unifi_create_client_group": _spec(_translate_create_client_group, "group_data"),
    "unifi_create_firewall_group": _spec(
        _pack_fields("group_data", frozenset({"name", "group_type", "group_members"})), "group_data"
    ),
    "unifi_create_firewall_zone": _spec(_translate_firewall_zone_crud, "name"),
    "unifi_update_firewall_zone": _spec(_translate_firewall_zone_crud, "zone_id", "name"),
    "unifi_delete_firewall_zone": _spec(_translate_firewall_zone_crud, "zone_id"),
    "unifi_create_oon_policy": _spec(_translate_create_oon_policy, "policy_data"),
    "unifi_create_port_forward": _spec(_translate_create_port_forward, "rule_data"),
    "unifi_create_simple_port_forward": _spec(_translate_create_simple_port_forward, "rule_data"),
    "unifi_create_qos_rule": _spec(_translate_create_qos_rule, "rule_data"),
    "unifi_create_simple_qos_rule": _spec(_translate_create_simple_qos_rule, "rule_data"),
    "unifi_create_port_profile": _spec(_translate_port_profile_create, "profile_data"),
    "unifi_create_route": _spec(
        _translate_route_args,
        "name",
        "static_route_network",
        "static_route_nexthop",
        "static_route_distance",
        "enabled",
        "route_type",
    ),
    "unifi_update_route": _spec(
        _translate_route_args,
        "route_id",
        "name",
        "static_route_network",
        "static_route_nexthop",
        "static_route_distance",
        "enabled",
    ),
    "unifi_update_autobackup_settings": _spec(_translate_autobackup_update, "settings"),
    "unifi_update_client_group": _spec(_translate_client_group_update, "group_id", "update_data"),
    "unifi_update_content_filter": _spec(_translate_content_filter_update, "filter_id", "update_data"),
    "unifi_update_dns_record": _spec(_translate_dns_update, "record_id", "record_data"),
    "unifi_update_oon_policy": _spec(_translate_oon_update, "policy_id", "update_data"),
    "unifi_update_port_forward": _spec(
        _translate_update_port_forward,
        "rule_id",
        "updates",
    ),
    "unifi_update_port_profile": _spec(_translate_port_profile_update, "profile_id", "update_data"),
    # Network read aliases, duration conversion, and wrapper-only filters.
    "unifi_get_alerts": _spec(_rename_and_drop(drop=frozenset({"limit"})), "include_archived"),
    "unifi_get_anomalies": _spec(lambda args: _translate_duration(args, default_hours=24), "duration_hours"),
    "unifi_get_client_details": _spec(
        _rename_and_drop(rename={"mac_address": "client_mac"}, drop=frozenset({"include", "summary"})),
        "client_mac",
    ),
    "unifi_get_client_dpi_traffic": _spec(_rename_and_drop(rename={"group_by": "by"}), "client_mac", "by"),
    "unifi_get_client_sessions": _spec(
        lambda args: _translate_duration(args, default_hours=24),
        "client_mac",
        "duration_hours",
        "limit",
    ),
    "unifi_get_client_stats": _spec(
        lambda args: _translate_duration(args, default_hours=1),
        "client_id",
        "duration_hours",
        "granularity",
    ),
    "unifi_get_dashboard": _spec(_rename_and_drop(drop=frozenset({"summary"})), "history_seconds"),
    "unifi_get_device_details": _spec(
        _rename_and_drop(rename={"mac_address": "device_mac"}, drop=frozenset({"include", "summary"})),
        "device_mac",
    ),
    "unifi_get_device_stats": _spec(
        lambda args: _translate_duration(args, default_hours=1, drop=frozenset({"device_type"})),
        "device_id",
        "duration_hours",
        "granularity",
    ),
    "unifi_get_gateway_stats": _spec(
        lambda args: _translate_duration(args, default_hours=24), "duration_hours", "granularity"
    ),
    "unifi_get_ips_events": _spec(lambda args: _translate_duration(args, default_hours=24), "duration_hours", "limit"),
    "unifi_get_network_details": _spec(_rename_and_drop(drop=frozenset({"include", "summary"})), "network_id"),
    "unifi_get_network_stats": _spec(
        lambda args: _translate_duration(args, default_hours=1), "duration_hours", "granularity"
    ),
    "unifi_get_site_dpi_traffic": _spec(_rename_and_drop(rename={"group_by": "by"}), "by"),
    "unifi_get_snmp_settings": _spec(_rename_and_drop(constants={"section": "snmp"}), "section"),
    "unifi_get_speedtest_results": _spec(lambda args: _translate_duration(args, default_hours=24), "duration_hours"),
    "unifi_get_traffic_flows": _spec(_translate_traffic_flows, "query"),
    "unifi_list_devices": _spec(
        _rename_and_drop(drop=frozenset({"device_type", "status", "search", "limit", "include_details", "summary"}))
    ),
    "unifi_list_firewall_policies": _spec(
        _rename_and_drop(drop=frozenset({"search", "action", "enabled_only", "limit", "summary"})),
        "include_predefined",
    ),
    "unifi_list_networks": _spec(_rename_and_drop(drop=frozenset({"fields", "limit", "purpose", "search"}))),
    "unifi_list_rogue_aps": _spec(
        _rename_and_drop(drop=frozenset({"channel", "limit", "min_signal", "offset", "summary"})),
        "within_hours",
    ),
    "unifi_list_wlans": _spec(_rename_and_drop(drop=frozenset({"enabled_only", "limit", "search"}))),
    # Network mutation payload transforms.
    "unifi_create_network": _spec(_translate_network_create, "network_data"),
    "unifi_update_network": _spec(_translate_network_update, "network_id", "update_data"),
    "unifi_create_wlan": _spec(_translate_wlan_create, "wlan_data"),
    "unifi_update_wlan": _spec(_translate_wlan_update, "wlan_id", "update_data"),
    "unifi_set_device_led": _spec(_translate_device_led, "device_mac", "led_override"),
    "unifi_set_jumbo_frames": _spec(_translate_jumbo_frames, "device_mac", "config_data"),
    "unifi_set_outlet_state": _spec(
        _rename_and_drop(rename={"mac_address": "device_mac"}),
        "device_mac",
        "outlet_index",
        "relay_state",
        "cycle_enabled",
    ),
    "unifi_update_snmp_settings": _spec(_translate_snmp_update, "section", "settings_data"),
    "unifi_update_switch_stp": _spec(_translate_switch_stp, "device_mac", "config_data"),
}
