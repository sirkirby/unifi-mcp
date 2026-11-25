<!-- mcp-name: io.github.sirkirby/unifi-innerspace-mcp -->
# UniFi InnerSpace MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server for UniFi InnerSpace, the floor-plan application that runs on a UniFi OS console. It lets an AI assistant read your project's floor plans, walls, placed devices, access points, switches and unplaced inventory, and, with confirmation, edit the layout: walls, wall types, attenuation objects, floor plan settings and the project unit.

[![PyPI](https://img.shields.io/pypi/v/unifi-innerspace-mcp)](https://pypi.org/project/unifi-innerspace-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)

The InnerSpace server is in beta. There is no plugin for it yet: add it to your MCP client with `uvx` or Docker, as described below.

## How it connects

InnerSpace is a separate application on the console, served under `/proxy/innerspace/`. This server logs in to the console with a username and password and reads and writes through that session. The destination is the console you name, and it is the only host the server contacts.

There is no API key setting. A console's local `UNIFI_API_KEY` is never read or sent to InnerSpace, and an InnerSpace controller on the API server needs a username and password too. The account must be able to open the InnerSpace application, for example a Super Admin.

## Install

**PyPI and Docker.**

```bash
# PyPI
uvx unifi-innerspace-mcp@latest
# or: pip install unifi-innerspace-mcp

# Docker
docker pull ghcr.io/sirkirby/unifi-innerspace-mcp:latest
```

There is no Claude Code, Codex or OpenClaw plugin for this server yet. Register it with your MCP client as shown in [Claude Desktop](#claude-desktop).

### Claude Desktop

Add to `claude_desktop_config.json`, with the password in a file only you can read:

```jsonc
{
  "mcpServers": {
    "unifi-innerspace": {
      "command": "uvx",
      "args": ["unifi-innerspace-mcp@latest"],
      "env": {
        "UNIFI_INNERSPACE_HOST": "192.168.1.1",
        "UNIFI_INNERSPACE_USERNAME": "innerspace-reader",
        "UNIFI_INNERSPACE_PASSWORD_FILE": "/Users/you/.config/unifi-mcp/innerspace-password"
      }
    }
  }
}
```

Use the `_FILE` or `_COMMAND` form rather than putting the password itself in the config file.

Without a host the server still starts. It answers the client in setup mode, offers only `innerspace_setup_status`, explains what to set, and makes no request. With a host that cannot be reached, it serves its tools anyway and each call returns fixed text until the console answers; the next call after that logs in once and succeeds.

### Install from source

For development, run it from a checkout. You need [uv](https://docs.astral.sh/uv/) and Python 3.13 or later.

```bash
git clone https://github.com/sirkirby/unifi-mcp.git
cd unifi-mcp
uv sync
export UNIFI_INNERSPACE_HOST=192.168.1.1
export UNIFI_INNERSPACE_USERNAME=innerspace-reader
export UNIFI_INNERSPACE_PASSWORD_FILE="$HOME/.config/unifi-mcp/innerspace-password"
uv run --package unifi-innerspace-mcp unifi-innerspace-mcp
```

## Configure

Set these variables in the server's process environment. The server does not load `.env` files from the working directory.

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_INNERSPACE_HOST` (or `UNIFI_HOST`) | none | Console address. Without it the server starts in setup mode and makes no request. |
| `UNIFI_INNERSPACE_USERNAME`, `UNIFI_INNERSPACE_PASSWORD` | none | Console login. `_FILE` and `_COMMAND` forms follow the shared [credential provider](../../docs/credential-providers.md) rules. |
| `UNIFI_INNERSPACE_PORT` | `443` | Console HTTPS port. |
| `UNIFI_INNERSPACE_VERIFY_SSL` | `false` | Verify the console certificate. |
| `UNIFI_INNERSPACE_SSL_FINGERPRINT` (or `UNIFI_SSL_FINGERPRINT`) | none | Pin the console certificate by SHA-256 fingerprint. |
| `UNIFI_INNERSPACE_REDACT_SENSITIVE_FIELDS` | `true` | Redact secret-looking fields in responses. |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | `lazy`, `eager` or `meta_only`. |
| `UNIFI_INNERSPACE_READ_ONLY` | `false` | Refuse every write, previews included. |
| `UNIFI_POLICY_INNERSPACE_<CATEGORY>_<ACTION>` | allowed | Turn off one kind of write; see [permissions](docs/permissions.md). |

With certificate checks off, the server logs one warning at its first connection. Pin the certificate or turn verification on; see [TLS verification](../../docs/tls-verification.md). The full list, including HTTP, diagnostics and tracing, is in [docs/configuration.md](docs/configuration.md).

HTTP is opt-in, listens on port 3005 by default, and takes a bearer token from `UNIFI_INNERSPACE_MCP_HTTP_AUTH_TOKEN` (or its `_FILE` form). The floor plans describe a building, so set a token before serving HTTP to anything but loopback. The opt-in `innerspace` Docker Compose profile builds the image from a checkout; see [Docker Compose](docs/configuration.md#docker-compose).

## Features

24 domain tools: nine reads and 15 writes. See [docs/tools.md](docs/tools.md).

| Read | What it returns |
|---|---|
| `innerspace_get_status` | Whether InnerSpace is installed and running on the console, its version and any update |
| `innerspace_get_project` | The project: title, floor plans with scale, wall types; optionally every shape |
| `innerspace_list_floor_plans` | Floor plans with scale, image size and the image's scale and offset |
| `innerspace_list_walls` | The walls of one floor plan |
| `innerspace_list_placed_devices` | Devices placed on one floor plan, with position and height |
| `innerspace_list_access_points` | Access points with position, height, azimuth and mount |
| `innerspace_list_switches` | Switches with position |
| `innerspace_list_inventory` | Adopted devices not yet placed on a plan |
| `innerspace_get_plan_asset` | One plan's image metadata and its resource URI; optionally the image, capped |

| Write | What it changes |
|---|---|
| `innerspace_create_walls`, `innerspace_update_walls`, `innerspace_remove_walls` | The walls of one floor plan |
| `innerspace_create_wall_type`, `innerspace_update_wall_type` | The project's wall types (custom materials) |
| `innerspace_create_attenuation_objects`, `innerspace_update_attenuation_objects`, `innerspace_remove_attenuation_objects` | Attenuation objects (areas that weaken the signal) on one plan |
| `innerspace_create_attenuation_object_type`, `innerspace_update_attenuation_object_type` | The project's attenuation-object types |
| `innerspace_rename_floor_plan`, `innerspace_set_floor_attenuation`, `innerspace_reorder_floor_plans`, `innerspace_set_plan_scale` | A plan's title, floor attenuation and scale line, and the order of the plans |
| `innerspace_set_project_unit` | The unit the app displays lengths in |

Every write returns a preview unless called with `confirm=true`, then reads the console back: a write the read-back does not show is reported as a failure, and an unknown outcome as a failure to read before retrying. Writes are refused while InnerSpace is not installed or not running. Policy gates and `UNIFI_INNERSPACE_READ_ONLY` apply as on the other servers; see [docs/permissions.md](docs/permissions.md).

A floor plan's image is available as an MCP resource, fetched on demand: `innerspace://plans/{plan_id}/image` for a PNG, `innerspace://plans/{plan_id}/image.jpg` for a JPEG. `innerspace_get_plan_asset` returns the right URI.

IDs returned here belong to the InnerSpace tool family. They are not the ids the Network, Protect, Access or Site Manager servers use, and there is no translation between them.

**Not supported:** creating or deleting floor plans, replacing or uploading plan images, removing wall types or attenuation-object types, placing or moving devices, support bundle, events or websocket stream, and anything outside InnerSpace. Presence of the application is checked at the first read, not probed at startup.

There is no support bundle: the bundle is one closed schema shared by the Network, Protect and Access servers, so adding a product changes that contract. Report an InnerSpace problem with the details in [Reporting a problem](docs/troubleshooting.md#reporting-a-problem).

The same nine reads and 15 writes are also available through [`unifi-api-server`](../api/README.md#innerspace-console-product), which never returns plan image bytes.

## Documentation

- [Configuration](docs/configuration.md): login, TLS, settings, HTTP, Docker Compose, registration modes
- [Permissions](docs/permissions.md): confirmation, policy gates, read-only mode, what limits access, redaction
- [Tool catalog](docs/tools.md): the 24 tools, arguments, the write results, coordinates and the image conversion
- [Troubleshooting](docs/troubleshooting.md): setup mode, access errors, not installed or not running, TLS
- [MCP discovery and meta-tools](../../docs/tool-index.md): `tools/list`, `innerspace_tool_index` and `innerspace_execute`

## Development

```bash
cd apps/innerspace
make test         # Run tests
make lint         # Lint
make format       # Format
make manifest     # Regenerate tools_manifest.json
make run          # Run the server locally (lazy mode)
make pre-commit   # Format, manifests, lint and test
```

See the root [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full monorepo workflow.

## License

[MIT](../../LICENSE)
