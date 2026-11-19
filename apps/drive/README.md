<!-- mcp-name: io.github.sirkirby/unifi-drive-mcp -->
# UniFi Drive MCP Server

<p align="center">
  <img src="../../assets/hero-drive.svg" alt="UniFi Drive MCP Server" width="720">
</p>

A [Model Context Protocol](https://modelcontextprotocol.io) server for **UniFi Drive**, the storage application on UniFi NAS consoles (UNAS Pro, UNAS Pro 8, and similar). It lets an AI assistant read storage pools, RAID state, disk SMART health and shared drives, and manage the NAS's file services: turn SMB, NFS or Time Machine on or off, and add, change or remove NFS client connections.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)

## Status: beta, not yet released

UniFi Drive has no published API. The endpoints this server uses were read from the Drive web app on a UNAS Pro 8 running UniFi OS 5.0.12, and every read was checked against that console. Another firmware may answer differently; a field the server does not recognize is left out rather than failing the call.

## What it will not do

Nothing here can lose data on the NAS. There are no tools to erase a disk, delete or create a storage pool, or delete a shared drive. The write tools only change who can reach the data (file services and NFS clients), and each one previews the change before it is made.

## The NAS is its own console

A UNAS is a separate UniFi OS console, not part of the gateway, and it is not reachable through the Network application. Point this server at the NAS itself and log in with a **local** UniFi OS account on it. A UI.com account with MFA cannot log in here.

## Install

```bash
# From source (needs uv and Python 3.13+)
git clone https://github.com/sirkirby/unifi-mcp.git
cd unifi-mcp
uv sync
UNIFI_DRIVE_HOST=192.168.1.20 \
UNIFI_DRIVE_USERNAME=mcp \
UNIFI_DRIVE_PASSWORD_FILE="$HOME/.config/unifi-mcp/drive-password" \
uv run --package unifi-drive-mcp unifi-drive-mcp
```

Without a host the server still starts. It answers the client in setup mode, offers only `drive_setup_status`, explains what to set, and makes no request. With a host it also makes no request at startup: the first tool call logs in.

### MCP client configuration

```json
{
  "mcpServers": {
    "unifi-drive": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/unifi-mcp", "--package", "unifi-drive-mcp", "unifi-drive-mcp"],
      "env": {
        "UNIFI_DRIVE_HOST": "192.168.1.20",
        "UNIFI_DRIVE_USERNAME": "mcp",
        "UNIFI_DRIVE_PASSWORD_FILE": "/Users/you/.config/unifi-mcp/drive-password"
      }
    }
  }
}
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_DRIVE_HOST` | unset | IP or hostname of the NAS. `UNIFI_HOST` is not used, because it names the gateway. |
| `UNIFI_DRIVE_USERNAME` | unset | Local UniFi OS username on the NAS (`UNIFI_USERNAME` is not used) |
| `UNIFI_DRIVE_PASSWORD` | unset | Its password (`UNIFI_PASSWORD` is not used). `_FILE` and `_COMMAND` spellings work. |
| `UNIFI_DRIVE_PORT` | `443` | HTTPS port of the NAS (`UNIFI_PORT` is not used) |
| `UNIFI_DRIVE_VERIFY_SSL` | `false` | Verify the NAS certificate against the system CAs |
| `UNIFI_DRIVE_SSL_FINGERPRINT` | unset | SHA-256 fingerprint of the NAS certificate; pins it and overrides `UNIFI_DRIVE_VERIFY_SSL`. `UNIFI_SSL_FINGERPRINT` is not used. |
| `UNIFI_DRIVE_TIMEOUT_SECONDS` | `30` | Seconds to wait for one response |
| `UNIFI_DRIVE_TOOL_PERMISSION_MODE` | `confirm` | `bypass` skips the previews (falls back to `UNIFI_TOOL_PERMISSION_MODE`) |
| `UNIFI_DRIVE_MCP_CONTENT_MODE` | `adaptive` | MCP content mode for this server |
| `UNIFI_DRIVE_REDACT_SENSITIVE_FIELDS` | `true` | Redact secret-named fields in responses |

HTTP transport, tool registration modes and diagnostics use the same `UNIFI_MCP_*` settings as the other servers; the Drive server's default HTTP port is 3004.

## Tools

Read-only:

| Tool | What it returns |
|------|-----------------|
| `drive_get_system_info` | Console name, model, MAC, firmware and available update, state, uptime, CPU, memory |
| `drive_list_storage_pools` | Pools with capacity and usage, and RAID groups: level in effect vs. configured, protection, rebuild/expansion progress |
| `drive_list_disks` | Drive bays and cache slots with model, serial, size, temperature, pool, hot-spare flags and SMART counters |
| `drive_list_shared_drives` | Shared drives with pool, usage, quota, encryption, snapshot and remote-backup flags |
| `drive_get_shared_drive` | One shared drive |
| `drive_get_file_services` | Whether SMB, NFS and Time Machine are on, and the interfaces clients connect to |
| `drive_list_nfs_connections` | NFS clients, the shared drives each may mount (rw/ro) and the export path to mount |

Write (preview first; `confirm=true` applies):

| Tool | Permission category | What it changes |
|------|---------------------|-----------------|
| `drive_set_file_service` | `file_services` (update) | Turns SMB, NFS or Time Machine on or off |
| `drive_add_nfs_connection` | `nfs_connections` (create) | Lets a new client mount one or more shared drives |
| `drive_update_nfs_connection` | `nfs_connections` (update) | Changes a client's shared drives or async writes |
| `drive_remove_nfs_connection` | `nfs_connections` (delete) | Stops a client from mounting anything |

See [docs/tools.md](docs/tools.md) for parameters and behavior.

### No support bundle

The Drive server has no `drive_get_support_bundle` tool. Support bundles are one closed privacy schema shared by the Network, Protect and Access servers (`unifi_core/support_bundle.py`), and Drive isn't part of it. Adding it would change that contract for all three servers. For a Drive problem, run `drive_get_system_info` for the firmware version, use `drive_setup_status` when the server is in setup mode, and fill in the bug form's fields by hand.

### NFS on UniFi Drive

- Drive keeps every NFS client in one list, and its API replaces that list as a whole. Each NFS tool reads the list, changes one client and writes the list back with every other client exactly as it was read, then reads it back to check. NFS writes run one at a time, and a write stops without writing if the list changed since it was planned.
- Before saving a new or changed client, the tools run Drive's own hostname check, as the web app does.
- A client mounts `<nas>:/var/nfs/shared/<Shared Drive Name>` over NFSv3. Drive maps every client user to one Drive user; there is no squash option to set.
- Turning NFS off with `drive_set_file_service` keeps the client list, so it applies again when NFS comes back on. The Drive web app clears the list instead.

### Policy gates

Writes can be switched off per category, for example:

```bash
UNIFI_POLICY_DRIVE_NFS_CONNECTIONS_DELETE=false   # no NFS client removal
UNIFI_POLICY_DRIVE_FILE_SERVICES_UPDATE=false     # no SMB/NFS/Time Machine toggles
UNIFI_POLICY_DRIVE_UPDATE=false                   # no updates of any kind on this server
```

## Usage examples

> "How full is the NAS, and is the pool protected yet?"

> "Show me the SMART health of every disk and flag anything with bad sectors."

> "Let 192.168.1.50 mount the Media shared drive read-only over NFS."

> "Which NFS clients can mount Shared_Drive?"
