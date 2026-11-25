# Permission System — Drive Server

The Drive server has 20 domain tools: sixteen reads and four writes. The writes change who can reach the data on the NAS, never the data itself. There is no tool that erases a disk, creates or deletes a storage pool, or creates or deletes a shared drive.

| Tool | Policy category | Action |
|---|---|---|
| `drive_get_system_info` | `system` | read |
| `drive_list_storage_pools`, `drive_get_storage_usage`, `drive_list_disks` | `storage` | read |
| `drive_list_shared_drives`, `drive_get_shared_drive` | `shared_drives` | read |
| `drive_get_file_services`, `drive_get_smb_advanced_settings`, `drive_get_rsync_settings` | `file_services` | read |
| `drive_set_file_service` | `file_services` | update |
| `drive_list_nfs_connections` | `nfs_connections` | read |
| `drive_add_nfs_connection` | `nfs_connections` | create |
| `drive_update_nfs_connection` | `nfs_connections` | update |
| `drive_remove_nfs_connection` | `nfs_connections` | delete |
| `drive_list_logs` | `logs` | read |
| `drive_get_network_throughput`, `drive_get_fan_profile`, `drive_get_disk_stats` | `performance` | read |
| `drive_get_snapshot_overview`, `drive_list_snapshots` | `snapshots` | read |

The reads are annotated `readOnlyHint: true` and need no confirmation. The writes follow the shared [permission system](../../../docs/permissions.md): a preview first, then the change on `confirm=true`.

## Preview, then confirm

Every write returns a preview (`"requires_confirmation": true`) unless it is called with `confirm=true`. The preview says what will change and adds warnings where a change has a side effect:

- Turning SMB off while Time Machine is on also turns Time Machine off, because Time Machine runs over SMB. Turning SMB back on leaves Time Machine off; turn it on again with `drive_set_file_service`. Turning Time Machine on while SMB is off is refused.
- Turning NFS off keeps the NFS client list, so the clients can mount again when NFS comes back on. The Drive web app clears the list instead.
- A client that matches every host (`*`, `0.0.0.0/0`, `::/0`) is allowed but warned about.
- Async writes are faster, but writes the NAS acknowledged before a power loss can be lost.

Confirmed writes run one at a time per server process, in the order they arrive, and each one reads the result back. An NFS write re-reads Drive's client list just before writing and stops, with nothing written, if the list changed since the preview, for example after an edit in the Drive web app.

| Variable | Default | Effect |
|---|---|---|
| `UNIFI_DRIVE_TOOL_PERMISSION_MODE` | `confirm` | `bypass` applies writes without a preview (falls back to `UNIFI_TOOL_PERMISSION_MODE`) |
| `UNIFI_DRIVE_REQUIRE_PREVIEW_TOKEN` | `false` | `true` makes `confirm=true` carry the `preview_token` its preview returned (falls back to `UNIFI_REQUIRE_PREVIEW_TOKEN`) |
| `UNIFI_DRIVE_READ_ONLY` | `false` | `true` refuses every write, whatever the policy gates say (falls back to `UNIFI_READ_ONLY`) |

## Policy gates

Policy gates switch actions off before anything is sent to the NAS. The most specific variable wins: `UNIFI_POLICY_DRIVE_<CATEGORY>_<ACTION>`, then `UNIFI_POLICY_DRIVE_<ACTION>`, then `UNIFI_POLICY_<ACTION>`. Every action is allowed unless a gate turns it off.

```bash
UNIFI_POLICY_DRIVE_NFS_CONNECTIONS_DELETE=false   # no NFS client removal
UNIFI_POLICY_DRIVE_NFS_CONNECTIONS_CREATE=false   # no new NFS clients
UNIFI_POLICY_DRIVE_FILE_SERVICES_UPDATE=false     # no SMB/NFS/Time Machine toggles
UNIFI_POLICY_DRIVE_UPDATE=false                   # no updates of any kind on this server
```

A gated call returns `success: false` naming the variable that re-enables the action. An unknown `UNIFI_POLICY_DRIVE_*` variable is reported at startup with the closest valid names.

## What controls access besides this server

- **The NAS account.** The server acts with the login you give it. A read needs an account that can open UniFi Drive; file service and NFS changes need an administrator of Drive, and the NAS refuses them with a 403 otherwise. A dedicated local account keeps the server's access separate from yours.
- **NFS itself.** An NFS client entry decides which hosts may mount a shared drive and whether read-write or read-only. Drive maps every NFS client user to one Drive user; there is no squash option to set. Only shared drives can be exported over NFS: a personal drive is refused before anything is sent.

## Meta-tools and read-only clients

In `lazy` mode the server lists only its meta-tools, like the Network, Protect and Access servers. `drive_tool_index` and `drive_batch_status` are marked read-only; `drive_execute`, `drive_batch`, `drive_batch_cancel` and `drive_load_tools` are not, because they can run a write. A client that approves only read-only tools without asking therefore asks before every Drive call made through `drive_execute`. To have the reads listed directly, use `eager` mode, optionally with `UNIFI_ENABLED_CATEGORIES=system,storage,shared_drives`.

## Common scenarios

### Read-only monitoring

```bash
UNIFI_DRIVE_READ_ONLY=true
```

The four writes are refused; every read works.

### NFS changes need a human, file services are off-limits

```bash
UNIFI_DRIVE_TOOL_PERMISSION_MODE=confirm          # the default
UNIFI_POLICY_DRIVE_FILE_SERVICES_UPDATE=false
```

### Serving HTTP to another machine

Anyone who can reach the endpoint can call the writes with the server's login. Set `UNIFI_DRIVE_MCP_HTTP_AUTH_TOKEN`, keep the bind on loopback behind an authenticating proxy, and consider `UNIFI_DRIVE_READ_ONLY=true`. See [HTTP transport](configuration.md#http-transport).

## Response redaction

`UNIFI_DRIVE_REDACT_SENSITIVE_FIELDS` (default `true`, falling back to `UNIFI_REDACT_SENSITIVE_FIELDS`) redacts fields whose names look secret, such as passwords and tokens, replacing their values with `***REDACTED***`. It does not mask MAC addresses, disk serial numbers, NFS client addresses or shared drive names: review results before you share them. `drive_get_system_info` drops the console's location, public IP and owner account before returning.
