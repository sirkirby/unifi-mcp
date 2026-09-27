# MAC parameter migration

The next minor Network and API releases rename the subject MAC parameter on 18 tools to `mac_address`. Update MCP tool calls and `/v1/actions/{tool_name}` request `args` together. The old names are rejected; there is no alias period. Other parameters, including `ap_mac` on RF scan tools, keep their existing meanings.

| Old parameter | Tools | New parameter |
| --- | --- | --- |
| `device_mac` | `unifi_configure_port_aggregation`, `unifi_configure_port_mirror`, `unifi_force_provision_device`, `unifi_get_lldp_neighbors`, `unifi_get_port_stats`, `unifi_get_switch_capabilities`, `unifi_get_switch_ports`, `unifi_locate_device`, `unifi_power_cycle_port`, `unifi_set_device_led`, `unifi_set_jumbo_frames`, `unifi_set_switch_port_profile`, `unifi_toggle_device`, `unifi_update_switch_stp` | `mac_address` |
| `client_mac` | `unifi_get_client_dpi_traffic`, `unifi_get_client_sessions`, `unifi_get_client_wifi_details` | `mac_address` |
| `mac` | `unifi_recent_events` | `mac_address` |

For example, call `unifi_get_switch_ports(mac_address="aa:bb:cc:dd:ee:ff")` or send `{"args":{"mac_address":"aa:bb:cc:dd:ee:ff"}}` to `/v1/actions/unifi_get_switch_ports`. `mac_address` remains optional on `unifi_get_client_sessions` and `unifi_recent_events`; omitting it keeps the all-clients or all-events behavior.

MCP rejection messages suggest `mac_address`. HTTP actions return the generic action-failure response for old names; the server audit log records the missing or unknown argument. Update stored action requests before upgrading.

Confirmation previews for `unifi_locate_device`, `unifi_force_provision_device`, `unifi_set_device_led`, and `unifi_toggle_device` also rename `resource_data.device_mac` to `resource_data.mac_address`. Ordinary result fields named `device_mac` or `client_mac` retain their names.
