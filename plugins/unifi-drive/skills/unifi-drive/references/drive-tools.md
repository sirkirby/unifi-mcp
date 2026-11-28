# Drive Server Tool Reference (22 domain tools, plus 6 meta-tools)

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
3 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_get_storage_usage` | Read | Returns each storage pool's capacity, used and free space, and what the used space is used by: personal drives, shared drives, Microsoft ... |
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
4 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_get_file_services` | Read | Returns whether SMB, NFS and Time Machine are enabled on the NAS, and the network interfaces (address, link speed) clients connect to. |
| `drive_get_rsync_settings` | Read | Returns whether the rsync service is on, whether a dedicated rsync account is set and its username (never its password), and whether SSH,... |
| `drive_get_smb_advanced_settings` | Read | Returns whether SMB Trash for personal drives is on (files removed over SMB go to Trash instead of being deleted) and whether every perso... |
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
1 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_list_logs` | Read | Lists the NAS's system log, newest first, as the Drive UI's System Log shows it: time, severity, category, type, event and message. |
<!-- /AUTO:tools:logs -->

## Performance

<!-- AUTO:tools:performance -->
3 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_get_disk_stats` | Read | Returns each disk's temperature, read and write throughput (KB/s) and bad sector count over the last `hours`, summarized per disk. |
| `drive_get_fan_profile` | Read | Returns the NAS's fan mode and the modes it offers, with the names the Drive web app shows (Cooling, Balanced, Quiet). |
| `drive_get_network_throughput` | Read | Returns the NAS's network throughput right now: data received and sent, in KB/s. |
<!-- /AUTO:tools:performance -->

## Snapshots

<!-- AUTO:tools:snapshots -->
2 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_get_snapshot_overview` | Read | Returns every shared and personal drive's snapshot settings and state: snapshot limit and count, locked and pending-deletion counts, spac... |
| `drive_list_snapshots` | Read | Lists one shared drive's snapshots, newest first (id, name, Drive's label, creation time, locked), by the shared drive's name from drive_... |
<!-- /AUTO:tools:snapshots -->

## Users and Groups

<!-- AUTO:tools:users -->
2 tools.

| Tool | Type | Description |
|------|------|-------------|
| `drive_list_groups` | Read | Lists the UniFi OS user groups that shared drive access can be granted to, with id and name. |
| `drive_list_users` | Read | Lists the NAS's users with username, full name, email, status, access level (owner, admin or user), console roles, personal drive and Act... |
<!-- /AUTO:tools:users -->
