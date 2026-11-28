# Drive Server Tool Reference (11 domain tools, plus 6 meta-tools)

UniFi Drive tools for a UniFi NAS, pinned to `unifi-drive-mcp==0.1.0`.
Writes preview by default and apply with `confirm=true`. These IDs are scoped
to the Drive tool family — do not pass them to Network, Protect or Access tools.

## Meta-Tools

| Tool | Purpose |
|---|---|
| `drive_tool_index` | Discover names and schemas |
| `drive_execute` | Dispatch one domain tool |
| `drive_load_tools` | Load selected lazy tools |
| `drive_batch` | Dispatch a bounded group of calls |
| `drive_batch_status` | Check dispatched jobs |
| `drive_batch_cancel` | Cancel dispatched jobs that have not started |

## System

<!-- AUTO:tools:system -->
1 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_get_system_info` | Read | Returns the NAS console's identity and health: name, model (e.g. |
<!-- /AUTO:tools:system -->

## Storage

<!-- AUTO:tools:storage -->
2 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_list_disks` | Read | Lists the NAS's drive bays and SSD cache slots with the disk in each, its pool membership and SMART health. |
| `drive_list_storage_pools` | Read | Lists storage pools with capacity, usage and status, and each pool's RAID groups: the RAID level in effect (current_level) versus the con... |
<!-- /AUTO:tools:storage -->

## Shared Drives

<!-- AUTO:tools:shared_drives -->
2 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_get_shared_drive` | Read | Returns one shared drive by ID (from drive_list_shared_drives). |
| `drive_list_shared_drives` | Read | Lists shared drives with their storage pool, usage, quota, status, encryption, snapshot and remote-backup flags. |
<!-- /AUTO:tools:shared_drives -->

## File Services

<!-- AUTO:tools:file_services -->
2 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_get_file_services` | Read | Returns whether SMB, NFS and Time Machine are enabled on the NAS, and the network interfaces (address, link speed) clients connect to. |
| `drive_set_file_service` | Mutate | Turns a file-sharing service on or off: smb, nfs or time_machine (Time Machine runs over SMB and needs SMB on). |
<!-- /AUTO:tools:file_services -->

## NFS Connections

<!-- AUTO:tools:nfs -->
4 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_list_nfs_connections` | Read | Lists the NFS clients allowed to mount shared drives, with the shared drives each may mount and the export path to mount. |
| `drive_add_nfs_connection` | Mutate | Allows a new NFS client (IP address or hostname) to mount one or more shared drives. |
| `drive_remove_nfs_connection` | Mutate | Removes an NFS client, so it can no longer mount any shared drive. |
| `drive_update_nfs_connection` | Mutate | Changes an existing NFS client's shared drives and/or async writes. |
<!-- /AUTO:tools:nfs -->

## Logs

<!-- AUTO:tools:logs -->
<!-- /AUTO:tools:logs -->

## Performance

<!-- AUTO:tools:performance -->
<!-- /AUTO:tools:performance -->

## Snapshots

<!-- AUTO:tools:snapshots -->
<!-- /AUTO:tools:snapshots -->

## Users and Groups

<!-- AUTO:tools:users -->
<!-- /AUTO:tools:users -->
