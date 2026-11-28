# UniFi Drive MCP tools

The Drive server has 12 domain tools: eight reads and four writes that preview first. The six shared meta-tools (`drive_tool_index`, `drive_execute`, `drive_batch`, `drive_batch_status`, `drive_batch_cancel`, `drive_load_tools`) are described in [MCP discovery and meta-tools](../../../docs/tool-index.md); permissions and policy gates are in [permissions.md](permissions.md).

Every tool returns `{"success": true, "data": ...}` or `{"success": false, "error": "..."}`. Write tools return a preview (`"requires_confirmation": true`) unless called with `confirm=true`, or the server runs in bypass mode.

Errors never contain the NAS address or credentials. A request that fails names its method, path and HTTP status, plus Drive's own error message when it sends one.

## System

### `drive_get_system_info`

No parameters. Reads `GET /api/system` and keeps only: `name`, `hostname`, `model`, `shortname`, `mac`, `firmware_version`, `firmware_update_available`, `device_state`, `is_setup`, `uptime_seconds`, `timezone`, `cpu_load`, `cpu_temperature_c`, `memory_total_kb`, `memory_available_kb`. The console's location, public IP and owner account are dropped.

## Storage

Both tools read `GET /proxy/drive/api/v2/storage`.

### `drive_list_storage_pools`

No parameters. Each pool has `id`, `number`, `status` (for example `noDataProtectionYet` while a RAID 5 pool has a single disk), `prefer_level`, `capacity_bytes`, `used_bytes`, `used_percent`, `initializing_status` and `raid_groups`. Each RAID group has `current_level` and `config_level` (they differ until the pool has enough disks or while it migrates), `current_protection` and `expected_protection` (disk failures survived), `recommended_disk_size`, and Drive's `progress` and `estimate` for a rebuild or expansion.

### `drive_list_disks`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `include_empty` | `false` | Also list empty bays and slots |
| `include_cache` | `true` | Include SSD cache slots |

Each entry has `slot_id`, `bay_type` (`disk` or `cache`), `state`, `pool_id`, `raid_group_id`, hot-spare flags, `type`, `model`, `serial`, `firmware`, `size_bytes`, `rpm`, `interface`, `sector_format`, `temperature_c`, and the SMART counters `power_on_hours`, `bad_sector_count`, `uncorrectable_sector_count`, `read_error_rate`, `smart_read_error_count`, plus `risk_reasons` and `incompatible_reasons`. An empty bay carries only its slot, type and state.

## Shared drives

### `drive_list_shared_drives`

No parameters. Each drive has `id`, `name`, `status`, `storage_pool_id`, `quota_bytes` (absent when unlimited), `used_bytes`, `role`, `member_count`, `encryption_status`, `snapshot_enabled` and `remote_backup_enabled`. The `id` is what the NFS tools take.

### `drive_get_shared_drive`

| Parameter | Description |
|-----------|-------------|
| `drive_id` | Shared drive ID from `drive_list_shared_drives` |

Drive's single-drive endpoint does not return the protection flags or member count.

## File services

### `drive_get_file_services`

No parameters. Returns `smb_enabled`, `nfs_enabled`, `time_machine_enabled`, `custom_domain` and `network_interfaces` (name, port type, link state and speed, address, MAC).

### `drive_set_file_service` (write)

| Parameter | Description |
|-----------|-------------|
| `service` | `smb`, `nfs` or `time_machine` |
| `enabled` | `true` to turn it on, `false` to turn it off |
| `confirm` | `false` (default) previews; `true` applies |

- Sends `PUT /proxy/drive/api/v1/services/<service>/settings` with `{"enable": ...}` and reads the setting back.
- Time Machine runs over SMB: turning it on while SMB is off is refused.
- Turning SMB off while Time Machine is on, or NFS off while clients are configured, adds a warning to the preview.
- Turning NFS on lists the clients that can mount again, with their shared drives and permissions.
- Turning NFS off keeps the NFS client list. The Drive web app clears it at that point; remove clients with `drive_remove_nfs_connection` if you want the same.
- Asking for the state the service is already in changes nothing and returns `changed: false`.

## NFS connections

`GET`/`PATCH /proxy/drive/api/v1/services/nfs/advanced-settings` hold every client in one list, and a `PATCH` of `connections` replaces the whole list while Drive keeps its other NFS settings (Drive refuses a `PUT` here). Each write tool reads the list, changes one client, sends every other client back exactly as it was read (including any setting this server does not know about), and reads the list again to check the result. If another client is missing afterwards, the tool reports it.

NFS writes from one server run one at a time. Just before the `PATCH`, a write reads the list once more and stops without writing if it changed since the change was planned, for example by an edit in the Drive web app. Run the tool again in that case.

### `drive_list_nfs_connections`

No parameters. Each connection has `client`, `async_writes`, `error_codes` and `shared_drives`; each shared drive has `id`, `name`, `status`, `encryption_status`, `permission` (`rw` or `ro`) and `export_path` (`/var/nfs/shared/<name>`).

### `drive_add_nfs_connection` (write)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `client` | required | Client IP address, hostname, CIDR range or `*` pattern |
| `shared_drives` | required | `[{"id": "<shared drive id>", "permission": "rw"}]`; `permission` is `rw` (default) or `ro` |
| `async_writes` | `false` | Async writes: faster, but writes acknowledged before a NAS power loss can be lost |
| `confirm` | `false` | `true` saves |

- `client` may contain only letters, digits and `. : / * - _`, or be an IP address or range (IPv6 such as `::1` included). Spaces, commas and parentheses are refused so the value cannot carry export options.
- A client that matches every host (`*`, `0.0.0.0/0`, `::/0`) is allowed but gets a warning in the preview.
- Unknown shared drive IDs and a client that already has a connection are refused.
- Only shared drives can be exported over NFS; a personal drive is refused before anything is sent.
- A `shared_drives` entry copied from `drive_list_nfs_connections` can be passed as is; its read-only fields are ignored.
- On confirm, the client name goes through Drive's `POST .../nfs/test-hostnames` check first, as in the web app. A client Drive flags is not saved.

### `drive_update_nfs_connection` (write)

| Parameter | Description |
|-----------|-------------|
| `client` | The client as listed |
| `shared_drives` | Replaces the client's whole shared drive list |
| `async_writes` | New async setting |
| `confirm` | `true` saves |

Pass only the fields you want to change — current values are automatically preserved. In `shared_drives`, a drive the client already has keeps its current permission when `permission` is left out; only a newly granted drive defaults to `rw`. To change the client address itself, remove the connection and add a new one.

### `drive_remove_nfs_connection` (write, destructive)

| Parameter | Description |
|-----------|-------------|
| `client` | The client as listed |
| `confirm` | `true` removes |

The client can no longer mount anything. No data on the shared drives is touched, and the other clients are kept.

## Logs

### `drive_list_logs`

Reads the system log the Drive web app shows under System Log, newest first, from `GET /proxy/drive/api/v2/systems/logs`. A log entry holds an event name and the values to fill in, so the tool also reads `GET /proxy/drive/api/v2/systems/log-definitions` for each event's title and text.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `50` | Most entries per page, 1 to 500 |
| `severities` | all | Any of `low`, `medium`, `high`, `very_high` |
| `category` | all | A category such as `activity`, `storage` or `settings` |
| `types` | all | Types such as `storagePool`, `drive`, `hotSpare`, `userAccess`, `fanMode` |
| `keyword` | none | Only entries whose text matches it |
| `scope` | `all` | `audit` for user and admin actions, `flow` for file activity |
| `after`, `before` | none | ISO 8601 times with an offset, such as `2026-11-20T00:00:00Z` |
| `cursor` | none | `next_cursor` from the previous page |

Each entry has `time` (ISO 8601 with the NAS's UTC offset), `severity`, `category`, `type`, `event` (such as `DriveInserted`), `title` and `message`. `message` is the sentence the web app shows, so it names the users, client addresses, drives and pools involved. Entry ids and the ids behind the web app's detail panels are left out.

`next_cursor` is set when there are more entries. Pass it back as `cursor` with the same filters: Drive ties a cursor to the filters it was returned with.

A category is sent to Drive as its list of types, because Drive ignores a category filter. Drive answers an unknown category or type with an empty list, so the tool checks both against the firmware's own definitions first and returns an error listing the valid values instead.
