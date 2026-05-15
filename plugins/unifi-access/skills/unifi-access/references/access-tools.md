# Access Server Tool Reference (34 tools)

Complete reference for `access_*` tools. All read tools are always available. All mutations are **disabled by default** — the user must explicitly enable them because Access controls physical door locks and building entry.

## Table of Contents
- [Meta-Tools](#meta-tools)
- [Doors](#doors)
- [Policies & Schedules](#policies--schedules)
- [Credentials](#credentials)
- [Visitors](#visitors)
- [Events](#events)
- [Devices](#devices)
- [System](#system)
- [Dual Authentication](#dual-authentication)
- [Common Scenarios](#common-scenarios)

---

## Meta-Tools

Always available, regardless of registration mode.

| Tool | Purpose |
|------|---------|
| `access_tool_index` | Discover tools (names+descriptions by default; pass `include_schemas` for full schemas) |
| `access_execute` | Execute any tool by name (essential in lazy mode) |
| `access_batch` | Run multiple tools in parallel |
| `access_batch_status` | Check status of an async batch job |

---

## Doors

<!-- AUTO:tools:doors -->
6 tools.

| Tool | Type | Description |
|------|------|-------------|
| `access_get_door` | Read | Returns detailed information for a single door including lock state, configuration, and connected devices. |
| `access_get_door_status` | Read | Returns the current lock and position status for a single door. |
| `access_list_door_groups` | Read | Lists all door groups configured on the Access controller. |
| `access_list_doors` | Read | Lists all doors managed by the Access controller with their name, lock state, and connection status. |
| `access_lock_door` | Mutate | Lock a door immediately. |
| `access_unlock_door` | Mutate | Unlock a door for a specified duration. |
<!-- /AUTO:tools:doors -->

**Tips:**
- `access_get_door_status` is lighter than `access_get_door` when you just need lock state
- `access_unlock_door` relocks automatically after the duration expires — default is 2 seconds
- Door operations are **physical real-world actions** — always preview first
- Lock/unlock requires the proxy session auth path (username + password, not API key alone)

**Permission env vars:**
- `UNIFI_POLICY_ACCESS_DOORS_UPDATE=true` — enables lock/unlock

---

## Policies & Schedules

<!-- AUTO:tools:policies -->
4 tools.

| Tool | Type | Description |
|------|------|-------------|
| `access_get_policy` | Read | Returns detailed information for a single access policy including assigned doors, schedule, user groups, and configuration. |
| `access_list_policies` | Read | Lists all access policies configured on the Access controller. |
| `access_list_schedules` | Read | Lists all access schedules configured on the Access controller. |
| `access_update_policy` | Mutate | Update an access policy's configuration. |
<!-- /AUTO:tools:policies -->

**Tips:**
- Policies connect doors to user groups with a schedule — they define "who can enter where and when"
- Changes take effect immediately for all users in the policy's groups
- Policy updates require the proxy session auth path

**Permission env vars:**
- `UNIFI_POLICY_ACCESS_POLICIES_UPDATE=true`

---

## Credentials

<!-- AUTO:tools:credentials -->
4 tools.

| Tool | Type | Description |
|------|------|-------------|
| `access_get_credential` | Read | Returns detailed information for a single access credential including type, status, assigned user, and creation date. |
| `access_list_credentials` | Read | Lists all access credentials (NFC cards, PINs, mobile credentials) with their type, status, and assigned user. |
| `access_create_credential` | Mutate | Create a new access credential (NFC card, PIN, or mobile credential) and assign it to a user. |
| `access_revoke_credential` | Mutate | Revoke (delete) an access credential. |
<!-- /AUTO:tools:credentials -->

**Tips:**
- Credential types: `nfc` (card/fob token), `pin` (numeric code), `mobile` (smartphone)
- Each type requires different data: NFC needs `{user_id, token}`, PIN needs `{user_id, pin_code}`, mobile needs `{user_id}`
- Revoking is permanent — the credential is deleted, not disabled
- Both create and revoke require the proxy session auth path

**Permission env vars:**
- `UNIFI_POLICY_ACCESS_CREDENTIALS_CREATE=true`
- `UNIFI_POLICY_ACCESS_CREDENTIALS_DELETE=true` (for revoke)

---

## Visitors

<!-- AUTO:tools:visitors -->
4 tools.

| Tool | Type | Description |
|------|------|-------------|
| `access_get_visitor` | Read | Returns detailed information for a single visitor pass including name, access time range, assigned doors, and status. |
| `access_list_visitors` | Read | Lists all visitor passes with their name, status, valid time range, and assigned doors. |
| `access_create_visitor` | Mutate | Create a new visitor pass with a name and access time range. |
| `access_delete_visitor` | Mutate | Delete a visitor pass. |
<!-- /AUTO:tools:visitors -->

**Tips:**
- Visitor passes are time-bounded — they automatically expire at `access_end`
- Times use ISO 8601 format: `2026-03-17T09:00:00Z`
- Include contact info (email/phone) for notification support
- Both create and delete require the proxy session auth path

**Permission env vars:**
- `UNIFI_POLICY_ACCESS_VISITORS_CREATE=true`
- `UNIFI_POLICY_ACCESS_VISITORS_DELETE=true`

---

## Events

<!-- AUTO:tools:events -->
5 tools.

| Tool | Type | Description |
|------|------|-------------|
| `access_get_activity_summary` | Read | Get an aggregated activity summary for Access events over a time period. |
| `access_get_event` | Read | Returns detailed information for a single access event including event type, door, user, timestamp, and result. |
| `access_list_events` | Read | Query access events from the controller with optional filters. |
| `access_recent_events` | Read | Get recent events from the in-memory websocket buffer. |
| `access_subscribe_events` | Read | Returns instructions for subscribing to real-time Access events. |
<!-- /AUTO:tools:events -->

**Tips:**
- **Real-time vs historical**: Use `access_recent_events` for "what just happened?" Use `access_list_events` for historical audit
- `access_get_activity_summary` provides high-level patterns (events per day, by type) — useful for security audits
- Event types for `access_recent_events` filtering: `door_open`, `door_close`, `access_granted`, `access_denied`, `door_alarm`
- `access_list_events` uses `topic` parameter: `admin` (default) or `admin_activity`
- `access_list_events` and `access_get_activity_summary` require the proxy session auth path

---

## Devices

<!-- AUTO:tools:devices -->
3 tools.

| Tool | Type | Description |
|------|------|-------------|
| `access_get_device` | Read | Returns detailed information for a single Access device including name, type, connection state, firmware version, MAC, and IP address. |
| `access_list_devices` | Read | Lists all Access hardware devices (hubs, readers, relays, intercoms) with their name, type, connection state, and firmware version. |
| `access_reboot_device` | Mutate | Reboot an Access hardware device (hub, reader, relay, intercom). |
<!-- /AUTO:tools:devices -->

**Tips:**
- Rebooting a hub affects all doors/readers connected to it
- Device types: hub, reader, relay, intercom
- Reboot requires the proxy session auth path

**Permission env vars:**
- `UNIFI_POLICY_ACCESS_DEVICES_UPDATE=true`

---

## System

<!-- AUTO:tools:system -->
3 tools.

| Tool | Type | Description |
|------|------|-------------|
| `access_get_health` | Read | Returns Access system health summary including API client and proxy session status. |
| `access_get_system_info` | Read | Returns Access controller model, firmware version, uptime, and connected device counts. |
| `access_list_users` | Read | Lists all users registered in the Access controller with their access credentials and groups. |
<!-- /AUTO:tools:system -->

**Tips:**
- `access_get_health` shows both auth path statuses — use this to diagnose connection problems
- `access_list_users` is essential for auditing who has physical access

---

## Dual Authentication

Access uses two independent authentication paths, which is unique among the three servers:

### API Key Path (Port 12445)
- Uses: `UNIFI_ACCESS_API_KEY`
- Supports: All read-only operations (listing doors, events, devices, credentials, users)
- Library: py-unifi-access

### Local Proxy Session (Port 443)
- Uses: `UNIFI_ACCESS_USERNAME` + `UNIFI_ACCESS_PASSWORD`
- Supports: All mutations (lock/unlock, create credentials, manage visitors, update policies)
- Also supports: Some read operations (events list, activity summary, door groups)
- Auth flow: UniFi OS Console login → proxy session via `/proxy/access/api/v2/...`

### What to Configure

| Use Case | API Key | Username + Password |
|----------|---------|---------------------|
| Read-only monitoring | Required | Not needed |
| Full access (read + write) | Optional | Required |
| Both paths for flexibility | Set both | Set both |

If mutations fail with auth errors, the user likely needs to set `UNIFI_ACCESS_USERNAME` and `UNIFI_ACCESS_PASSWORD` — API key alone isn't enough for write operations.

---

## Common Scenarios

### "Who entered the building today?"
1. `access_list_events(start="<today 00:00>")` → all access events today
2. `access_get_activity_summary(days=1)` → high-level counts by type

### "Let someone in"
1. `access_list_doors` → find the right door
2. `access_get_door_status(door_id="...")` → verify current state
3. `access_unlock_door(door_id="...", duration=5)` → preview, then confirm

### "Create a visitor pass for tomorrow"
1. `access_create_visitor(name="Jane Smith", access_start="2026-03-18T09:00:00Z", access_end="2026-03-18T17:00:00Z", email="jane@example.com")` → preview
2. Confirm after review

### "Issue a new PIN credential"
1. `access_list_users` → find the user
2. `access_create_credential(credential_type="pin", credential_data={"user_id": "...", "pin_code": "1234"})` → preview
3. Confirm after review

### "Security audit — who has access?"
```
access_batch(tools=[
    {"tool": "access_list_users"},
    {"tool": "access_list_credentials"},
    {"tool": "access_list_policies"},
    {"tool": "access_list_doors"},
    {"tool": "access_get_activity_summary", "args": {"days": 30}}
])
```

### "A door reader seems offline"
1. `access_list_devices` → check device connection state
2. `access_get_device(device_id="...")` → detailed status including IP/MAC
3. Cross-reference with Network: `unifi_lookup_by_ip(ip="<reader IP>")` → check network connectivity
4. If needed: `access_reboot_device(device_id="...", confirm=true)` → reboot (requires permission)

### "Lock everything down"
1. `access_list_doors` → get all door IDs
2. Lock each door via batch:
```
access_batch(tools=[
    {"tool": "access_lock_door", "args": {"door_id": "door-1-uuid", "confirm": true}},
    {"tool": "access_lock_door", "args": {"door_id": "door-2-uuid", "confirm": true}}
])
```
