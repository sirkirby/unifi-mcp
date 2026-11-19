# UniFi Drive MCP tools

Every tool returns `{"success": true, "data": ...}` or `{"success": false, "error": "..."}`.

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

## NFS connections

### `drive_list_nfs_connections`

No parameters. Each connection has `client`, `async_writes`, `error_codes` and `shared_drives`; each shared drive has `id`, `name`, `status`, `encryption_status`, `permission` (`rw` or `ro`) and `export_path` (`/var/nfs/shared/<name>`).
