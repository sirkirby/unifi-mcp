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
"""

from __future__ import annotations

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
    "unifi_update_wlan": ("network_manager", "update_wlan"),
    "unifi_toggle_wlan": ("network_manager", "toggle_wlan"),
    "unifi_delete_wlan": ("network_manager", "delete_wlan"),
    "unifi_update_ap_group": ("network_manager", "update_ap_group"),
    "unifi_delete_ap_group": ("network_manager", "delete_ap_group"),
    # Firewall: tool layer pre-fetches list to find policy by id.
    "unifi_toggle_firewall_policy": ("firewall_manager", "toggle_firewall_policy"),
    "unifi_update_firewall_policy": ("firewall_manager", "update_firewall_policy"),
    # Toggle tools: tool body needs current enabled flag to compute new state.
    "unifi_toggle_port_forward": ("firewall_manager", "toggle_port_forward"),
    "unifi_toggle_qos_rule_enabled": ("qos_manager", "update_qos_rule"),
    "unifi_toggle_oon_policy": ("oon_manager", "toggle_oon_policy"),
    "unifi_toggle_traffic_route": ("traffic_route_manager", "toggle_traffic_route"),
    # update_device_radio: tool needs current radio_table to identify target band.
    "unifi_update_device_radio": ("device_manager", "update_device_radio"),
    # Stats: tool combines existence check on client/device with stats fetch.
    "unifi_get_device_stats": ("stats_manager", "get_device_stats"),
    "unifi_get_client_stats": ("stats_manager", "get_client_stats"),
    "unifi_get_top_clients": ("stats_manager", "get_top_clients"),
    # =========================================================================
    # Protect — preview/execute split (preview_X + X, X + apply_X patterns)
    # =========================================================================
    "protect_alarm_arm": ("alarm_manager", "arm"),
    "protect_alarm_disarm": ("alarm_manager", "disarm"),
    "protect_ptz_move": ("camera_manager", "ptz_move"),
    "protect_ptz_preset": ("camera_manager", "ptz_goto_preset"),
    "protect_ptz_zoom": ("camera_manager", "ptz_zoom"),
    "protect_reboot_camera": ("camera_manager", "apply_reboot_camera"),
    "protect_toggle_recording": ("camera_manager", "apply_toggle_recording"),
    "protect_update_camera_settings": ("camera_manager", "update_camera_settings"),
    "protect_update_chime": ("chime_manager", "apply_chime_settings"),
    "protect_update_light": ("light_manager", "apply_light_settings"),
    "protect_acknowledge_event": ("event_manager", "apply_acknowledge_event"),
    # =========================================================================
    # Access — preview/execute split (X + apply_X)
    # =========================================================================
    "access_create_credential": ("credential_manager", "apply_create_credential"),
    "access_revoke_credential": ("credential_manager", "apply_revoke_credential"),
    "access_reboot_device": ("device_manager", "apply_reboot_device"),
    "access_lock_door": ("door_manager", "apply_lock_door"),
    "access_unlock_door": ("door_manager", "apply_unlock_door"),
    "access_update_policy": ("policy_manager", "apply_update_policy"),
    "access_create_visitor": ("visitor_manager", "apply_create_visitor"),
    "access_delete_visitor": ("visitor_manager", "apply_delete_visitor"),
}
