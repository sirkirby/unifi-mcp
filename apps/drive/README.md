<!-- mcp-name: io.github.sirkirby/unifi-drive-mcp -->
# UniFi Drive MCP Server

<p align="center">
  <img src="../../assets/hero-drive.svg" alt="UniFi Drive MCP Server" width="720">
</p>

A [Model Context Protocol](https://modelcontextprotocol.io) server for **UniFi Drive**, the storage application on UniFi NAS consoles (UNAS Pro, UNAS Pro 8, and similar). It lets an AI assistant read storage pools, RAID state, disk SMART health and shared drives, and manage the NAS's file services: turn SMB, NFS or Time Machine on or off, and add, change or remove NFS client connections.

[![PyPI](https://img.shields.io/pypi/v/unifi-drive-mcp)](https://pypi.org/project/unifi-drive-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)

## Status: beta

UniFi Drive has no published API. The endpoints this server uses were read from the Drive web app on a UNAS Pro 8 running UniFi OS 5.0.12, and every read was checked against that console. Another firmware may answer differently; a field the server does not recognize is left out rather than failing the call.

## What it will not do

Nothing here can lose data on the NAS. There are no tools to erase a disk, delete or create a storage pool, or delete a shared drive. The write tools only change who can reach the data (file services and NFS clients), and each one previews the change before it is made.

## The NAS is its own console

A UNAS is a separate UniFi OS console, not part of the gateway, and it is not reachable through the Network application. Point this server at the NAS itself and log in with a **local** UniFi OS account on it. A UI.com account with MFA cannot log in here. The server reads its host, port and login from `UNIFI_DRIVE_*` only: the shared `UNIFI_HOST`, `UNIFI_USERNAME` and `UNIFI_PASSWORD` name the gateway and are never used or sent to the NAS.

## Install

### Claude Code plugin (recommended)

```
/plugin marketplace add sirkirby/unifi-mcp
/plugin install unifi-drive@unifi-plugins
```

Then run the plugin's setup skill: it asks for the NAS address and a local account on the NAS, and keeps the password in a credential provider rather than in the config. In Codex, install `unifi-drive` from the UniFi MCP marketplace in `/plugins`.

### PyPI and Docker

```bash
# PyPI
uvx unifi-drive-mcp@latest
# or: pip install unifi-drive-mcp

# Docker
docker pull ghcr.io/sirkirby/unifi-drive-mcp:latest
```

### Claude Desktop

Add to `claude_desktop_config.json`, with the password in a file only you can read:

```jsonc
{
  "mcpServers": {
    "unifi-drive": {
      "command": "uvx",
      "args": ["unifi-drive-mcp@latest"],
      "env": {
        "UNIFI_DRIVE_HOST": "192.168.1.20",
        "UNIFI_DRIVE_USERNAME": "mcp",
        "UNIFI_DRIVE_PASSWORD_FILE": "/Users/you/.config/unifi-mcp/drive-password"
      }
    }
  }
}
```

Use the `_FILE` or `_COMMAND` form rather than putting the password itself in the config file.

Without a host the server still starts. It answers the client in setup mode, offers only `drive_setup_status`, explains what to set, and makes no request. With a host it also makes no request at startup: the first tool call logs in.

### Install from source

For development, run it from a checkout. You need [uv](https://docs.astral.sh/uv/) and Python 3.13 or later.

```bash
git clone https://github.com/sirkirby/unifi-mcp.git
cd unifi-mcp
uv sync
export UNIFI_DRIVE_HOST=192.168.1.20
export UNIFI_DRIVE_USERNAME=mcp
export UNIFI_DRIVE_PASSWORD_FILE="$HOME/.config/unifi-mcp/drive-password"
uv run --package unifi-drive-mcp unifi-drive-mcp
```

## Configuration

Set these variables in the server's process environment. The server does not load `.env` files from the working directory.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_DRIVE_HOST` | unset | IP or hostname of the NAS. `UNIFI_HOST` is not used, because it names the gateway. Without it the server starts in setup mode. |
| `UNIFI_DRIVE_USERNAME` | unset | Local UniFi OS username on the NAS (`UNIFI_USERNAME` is not used) |
| `UNIFI_DRIVE_PASSWORD` | unset | Its password (`UNIFI_PASSWORD` is not used). `_FILE` and `_COMMAND` spellings work. |
| `UNIFI_DRIVE_PORT` | `443` | HTTPS port of the NAS (`UNIFI_PORT` is not used) |
| `UNIFI_DRIVE_VERIFY_SSL` | `false` | Verify the NAS certificate against the system CAs (falls back to `UNIFI_VERIFY_SSL`) |
| `UNIFI_DRIVE_SSL_FINGERPRINT` | unset | SHA-256 fingerprint of the NAS certificate; pins it and overrides `UNIFI_DRIVE_VERIFY_SSL`. `UNIFI_SSL_FINGERPRINT` is not used. |
| `UNIFI_DRIVE_TIMEOUT_SECONDS` | `30` | Seconds to wait for one response |
| `UNIFI_DRIVE_TOOL_PERMISSION_MODE` | `confirm` | `bypass` skips the previews (falls back to `UNIFI_TOOL_PERMISSION_MODE`) |
| `UNIFI_DRIVE_MCP_CONTENT_MODE` | `adaptive` | MCP content mode for this server |
| `UNIFI_DRIVE_REDACT_SENSITIVE_FIELDS` | `true` | Redact secret-named fields in responses |

With certificate checks off, the server logs one warning at startup. Pin the certificate or turn verification on; see [TLS verification](../../docs/tls-verification.md). The full list, including the NAS operation gate, HTTP, diagnostics and tracing, is in [docs/configuration.md](docs/configuration.md).

HTTP is opt-in, listens on port 3004 by default, and takes a bearer token from `UNIFI_DRIVE_MCP_HTTP_AUTH_TOKEN` (or its `_FILE` form; falls back to `UNIFI_MCP_HTTP_AUTH_TOKEN`). `UNIFI_DRIVE_MCP_HTTP_AUTH_TRUSTED_NETWORKS` names an authenticating proxy's address that skips the token for this server only. Anyone who reaches the endpoint can call the write tools, so set a token before serving HTTP to anything but loopback. The opt-in `drive` Docker Compose profile builds the image from a checkout; see [Docker Compose](docs/configuration.md#docker-compose). The Cloud Relay does not include this server unless you add it to `UNIFI_RELAY_SERVERS`.

### NAS operation gate

Every tool call takes a slot at this server's operation gate for the NAS before it reaches the NAS. Reads run side by side up to a cap, and confirmed writes run one at a time in the order they arrive. The guarantee is per server process: two servers, or two copies of one, pointed at the same NAS do not coordinate. `UNIFI_DRIVE_WRITE_HOLD_SECONDS` (default 120), `UNIFI_DRIVE_CALL_WAIT_SECONDS` (25) and `UNIFI_DRIVE_READ_CONCURRENCY` (8) tune it, falling back to the shared `UNIFI_*` values. A call refused as busy sends nothing to the NAS and says so. See [docs/configuration.md](docs/configuration.md#nas-operation-gate) for the write outcomes (`mutation_applied`).

## Tools

Read-only:

| Tool | What it returns |
|------|-----------------|
| `drive_get_system_info` | Console name, model, MAC, firmware and available update, state, uptime, CPU, memory |
| `drive_list_storage_pools` | Pools with capacity and usage, and RAID groups: level in effect vs. configured, protection, rebuild/expansion progress |
| `drive_get_storage_usage` | Per pool capacity, used and free space, split into personal drives, shared drives, Microsoft 365 backups, snapshots and system |
| `drive_list_disks` | Drive bays and cache slots with model, serial, size, temperature, pool, hot-spare flags and SMART counters |
| `drive_list_shared_drives` | Shared drives with pool, usage, quota, encryption, snapshot and remote-backup flags |
| `drive_get_shared_drive` | One shared drive |
| `drive_get_file_services` | Whether SMB, NFS and Time Machine are on, and the interfaces clients connect to |
| `drive_get_smb_advanced_settings` | Whether SMB Trash for personal drives is on, and its status |
| `drive_get_rsync_settings` | Whether rsync is on, whether an rsync account is set (username only), and whether SSH is on |
| `drive_list_nfs_connections` | NFS clients, the shared drives each may mount (rw/ro) and the export path to mount |
| `drive_list_logs` | The system log, newest first: time, severity, category, type, event and message, with filters and paging |
| `drive_get_network_throughput` | Network data received and sent right now, in KB/s |
| `drive_get_fan_profile` | Fan mode in effect (Cooling, Balanced or Quiet) and the modes offered |
| `drive_get_disk_stats` | Each disk's temperature, read/write throughput and bad sectors over the last hours or days |
| `drive_get_snapshot_overview` | Each shared and personal drive's snapshot limit and count, locked and pending-deletion counts, space held, last and next snapshot, pause state and reason, and schedule |
| `drive_list_snapshots` | One shared drive's snapshots, by the drive's name: id, name, creation time, locked |
| `drive_list_users` | Users with username, full name, email, status, access level (owner, admin or user), console roles and last login |
| `drive_list_groups` | UniFi OS user groups that shared drive access can be granted to |

Write (preview first; `confirm=true` applies):

| Tool | Permission category | What it changes |
|------|---------------------|-----------------|
| `drive_set_file_service` | `file_services` (update) | Turns SMB, NFS or Time Machine on or off |
| `drive_add_nfs_connection` | `nfs_connections` (create) | Lets a new client mount one or more shared drives |
| `drive_update_nfs_connection` | `nfs_connections` (update) | Changes a client's shared drives or async writes |
| `drive_remove_nfs_connection` | `nfs_connections` (delete) | Stops a client from mounting anything |

See [docs/tools.md](docs/tools.md) for parameters and behavior. IDs returned here belong to the Drive tool family; do not pass them to the Network, Protect, Access, Site Manager or InnerSpace servers.

The same eleven tools are also available through [`unifi-api-server`](../api/README.md#unifi-drive-console-product): REST and GraphQL for the reads, catalog actions for all of them. Its write preview is request-only, and it honours `UNIFI_DRIVE_READ_ONLY` but not the `UNIFI_POLICY_DRIVE_*` gates.

### No support bundle

The Drive server has no `drive_get_support_bundle` tool. Support bundles are one closed privacy schema shared by the Network, Protect and Access servers (`unifi_core/support_bundle.py`), and Drive isn't part of it. Adding it would change that contract for all three servers. For a Drive problem, run `drive_get_system_info` for the firmware version, use `drive_setup_status` when the server is in setup mode, and fill in the bug form's fields by hand; see [Reporting a problem](docs/troubleshooting.md#reporting-a-problem).

### NFS on UniFi Drive

- Drive keeps every NFS client in one list, and its API replaces that list as a whole. Each NFS tool reads the list, changes one client and writes the list back with every other client exactly as it was read, then reads it back to check. Confirmed writes from one server run one at a time, and a write stops without writing if the list changed since it was planned.
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

`UNIFI_DRIVE_READ_ONLY=true` refuses every write. See [docs/permissions.md](docs/permissions.md).

## Usage examples

> "How full is the NAS, and is the pool protected yet?"

> "Show me the SMART health of every disk and flag anything with bad sectors."

> "Let 192.168.1.50 mount the Media shared drive read-only over NFS."

> "Which NFS clients can mount Shared_Drive?"

> "Which disk was busiest over the last day, and how hot did it get?"

## Documentation

- [Configuration](docs/configuration.md): the NAS login, TLS, settings, operation gate, HTTP, Docker Compose, registration modes
- [Permissions](docs/permissions.md): previews, permission mode, policy gates, read-only mode, redaction
- [Tool catalog](docs/tools.md): the 22 tools, parameters, NFS behavior and write previews
- [Troubleshooting](docs/troubleshooting.md): setup mode, login and access errors, file services and NFS, TLS, Docker
- [MCP discovery and meta-tools](../../docs/tool-index.md): `tools/list`, `drive_tool_index` and `drive_execute`

## Development

```bash
cd apps/drive
make test         # Run tests
make lint         # Lint
make format       # Format
make manifest     # Regenerate tools_manifest.json
make run          # Run the server locally
make pre-commit   # Format, manifests, lint and test
```

See the root [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full monorepo workflow.

## License

[MIT](../../LICENSE)
