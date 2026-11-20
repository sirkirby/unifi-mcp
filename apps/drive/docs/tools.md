# UniFi Drive MCP tools

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

`GET`/`PUT /proxy/drive/api/v1/services/nfs/advanced-settings` hold every client in one list, and the `PUT` replaces the whole list. Each write tool reads the list, changes one client, sends every other client back exactly as it was read (including any setting this server does not know about), and reads the list again to check the result. If another client is missing afterwards, the tool reports it.

NFS writes from one server run one at a time. Just before the `PUT`, a write reads the list once more and stops without writing if it changed since the change was planned, for example by an edit in the Drive web app. Run the tool again in that case.

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
