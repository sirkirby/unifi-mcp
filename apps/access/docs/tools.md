# Tool Catalog

The UniFi Access MCP server exposes 34 tools, all prefixed with `access_`. Read-only tools are always available. Mutating tools are controlled by the [permission system](permissions.md).

Standard MCP clients should use `tools/list` for currently registered tools. For compact manifest-backed metadata in lazy/meta-only workflows, call the `access_tool_index` compatibility meta-tool at runtime, or inspect `src/unifi_access_mcp/tools_manifest.json`.

## Meta-Tools

These are always registered regardless of mode:

- `access_tool_index` -- Discover tools (names+descriptions by default; use `category`/`search`/`include_schemas` to filter)
- `access_execute` -- Execute a tool by name (for lazy/meta_only modes)
- `access_batch` -- Execute multiple tools in parallel
- `access_batch_status` -- Check batch job status

In lazy mode, an additional meta-tool is available:

- `access_load_tools` -- Load a set of tools by category or name for direct calling

## Doors (6 tools)

- `access_list_doors` -- List all doors with name, lock state, and connection status
- `access_get_door` -- Detailed door info: lock state, configuration, connected devices
- `access_get_door_status` -- Lightweight lock and position status for a single door
- `access_list_door_groups` -- List all door groups (used for policy assignment). Proxy session only.
- `access_unlock_door` -- Unlock a door for a specified duration (default 2s). Confirm required. Proxy session only.
- `access_lock_door` -- Lock a door immediately. Confirm required. Proxy session only.

## Events (5 tools)

- `access_list_events` -- Query events with filters (time range, door, user, limit). For historical data.
- `access_get_event` -- Single event details by ID (type, door, user, timestamp, result)
- `access_recent_events` -- Get events from the in-memory websocket buffer (fast, no API call)
- `access_subscribe_events` -- Get instructions for real-time event subscription via MCP resources
- `access_get_activity_summary` -- Aggregated activity summary over a time period with breakdowns by type. Proxy session only.

## Policies (4 tools)

- `access_list_policies` -- List all access policies with assigned doors, schedules, and user groups
- `access_get_policy` -- Detailed policy info: doors, schedule, user groups, configuration
- `access_list_schedules` -- List all access schedules
- `access_update_policy` -- Update policy name, doors, schedule, or user groups. Confirm required. Proxy session only.

## Credentials (4 tools)

- `access_list_credentials` -- List all credentials (NFC cards, PINs, mobile) with type, status, and user
- `access_get_credential` -- Detailed credential info: type, status, assigned user, creation date
- `access_create_credential` -- Create NFC card, PIN, or mobile credential. Confirm required. Proxy session only.
- `access_revoke_credential` -- Permanently revoke a credential. Confirm required. Proxy session only.

## Visitors (4 tools)

- `access_list_visitors` -- List all visitor passes with name, status, time range, and doors
- `access_get_visitor` -- Detailed visitor pass info: name, access period, doors, status
- `access_create_visitor` -- Create a time-bounded visitor pass with optional doors and contact info. Confirm required. Proxy session only.
- `access_delete_visitor` -- Permanently remove a visitor pass. Confirm required. Proxy session only.

## Devices (3 tools)

- `access_list_devices` -- List all hardware (hubs, readers, relays, intercoms) with type, state, firmware
- `access_get_device` -- Detailed device info: name, type, connection state, firmware, MAC, IP
- `access_reboot_device` -- Reboot an access device (temporarily offline during reboot). Confirm required. Proxy session only.

## System (3 tools)

- `access_get_system_info` -- Controller model, firmware, uptime, connected device counts
- `access_get_health` -- API client and proxy session status for connectivity diagnostics
- `access_list_users` -- List all registered users with access credentials and groups

## MCP Resources

In addition to tools, the server registers MCP resources for data that benefits from polling:

| Resource URI | Type | Description |
|-------------|------|-------------|
| `access://events/stream` | JSON | Recent events from the websocket buffer |
| `access://events/stream/summary` | JSON | Event count summary by type and door |

See [events.md](events.md) for details on the event streaming resources.
