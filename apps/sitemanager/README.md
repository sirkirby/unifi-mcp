<!-- mcp-name: io.github.sirkirby/unifi-sitemanager-mcp -->
# UniFi Site Manager MCP Server

<p align="center">
  <img src="../../assets/hero-sitemanager.svg" alt="UniFi Site Manager MCP Server" width="720">
</p>

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server for Ubiquiti's official [Site Manager API](https://developer.ui.com/site-manager-api/). It gives an AI assistant the account-wide view that the Network, Protect and Access servers cannot see from inside one console: every host, site and device on a UI account, WAN performance per site, and SD-WAN configurations.

[![PyPI](https://img.shields.io/pypi/v/unifi-sitemanager-mcp)](https://pypi.org/project/unifi-sitemanager-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)

## This server talks to Ubiquiti's cloud

The other servers in this project connect directly to a console you name. This one is different:

- Every request goes to `https://api.ui.com`. The destination is fixed and cannot be changed by configuration.
- It authenticates with a Site Manager API key, which covers every console the account can see.
- It is read-only. The Site Manager API has no write operations, and neither does this server.

## Install

**Claude Code plugin.**

```
/plugin marketplace add sirkirby/unifi-mcp
/plugin install unifi-sitemanager@unifi-plugins
```

Then run the plugin's setup command to configure the Site Manager key, and start a new Claude Code session. Give the key as a file or command provider; do not paste it into chat.

**Codex plugin.** Register the marketplace, then install `unifi-sitemanager` from Codex's `/plugins` UI:

```bash
codex plugin marketplace add sirkirby/unifi-mcp
```

Setup writes the key provider to a per-user settings file that the plugin's server entry reads through `UNIFI_SETTINGS_FILE`. See the [plugin support matrix](../../docs/plugin-support.md).

**PyPI and Docker.**

```bash
# PyPI
uvx unifi-sitemanager-mcp@latest
# or: pip install unifi-sitemanager-mcp

# Docker
docker pull ghcr.io/sirkirby/unifi-sitemanager-mcp:latest
```

### Install from source

You need [uv](https://docs.astral.sh/uv/) and Python 3.13 or later.

```bash
git clone https://github.com/sirkirby/unifi-mcp.git
cd unifi-mcp
uv sync
```

Create an API key at [unifi.ui.com](https://unifi.ui.com) under Settings > API Keys, save it in a file only you can read, and start the server:

```bash
export UNIFI_SITEMANAGER_API_KEY_FILE="$HOME/.config/unifi-mcp/sitemanager-api-key"
uv run --package unifi-sitemanager-mcp unifi-sitemanager-mcp
```

Without a key the server still starts. It answers the client in setup mode, offers only `sitemanager_setup_status`, explains what to set, and makes no request.

## Usage Examples

Once connected, ask in natural language:

> "List every console on my UniFi account with its OS version and whether it is connected"

> "Which devices across all my sites have a firmware update available?"

> "Which sites had WAN downtime or high latency in the last 24 hours?"

> "Compare packet loss over the last 7 days for the two sites on the same ISP"

> "Show the deployment status of my SD-WAN configuration. Are any hubs or spokes reporting errors?"

Every tool reads. Nothing on this server changes a console, a site or the account.

## Configure

Set these variables in the server's process environment. The server does not load `.env` files from the working directory. Load a trusted env file explicitly in your launcher, or name a per-user settings file with an absolute `UNIFI_SETTINGS_FILE` path.

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_SITEMANAGER_API_KEY` | none | Site Manager API key. Also accepted as `UNIFI_SITEMANAGER_API_KEY_FILE` or `UNIFI_SITEMANAGER_API_KEY_COMMAND`; set exactly one. |
| `UNIFI_SITEMANAGER_TIMEOUT_SECONDS` | `30` | Seconds to wait for one API response. |
| `UNIFI_SITEMANAGER_REDACT_SENSITIVE_FIELDS` | `true` | Redact secret-looking fields in responses. |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | `lazy`, `eager` or `meta_only`. |

The full list, including HTTP, logging, diagnostics and tracing, is in [docs/configuration.md](docs/configuration.md). The `_FILE` and `_COMMAND` forms follow the shared [credential provider](../../docs/credential-providers.md) rules.

### MCP response size

`UNIFI_SITEMANAGER_MCP_CONTENT_MODE` (falling back to `UNIFI_MCP_CONTENT_MODE`) controls how tool results are returned. The default, `adaptive`, decides from the MCP `protocolVersion` the client advertised during initialization, not from the client's name. Clients advertising `2025-06-18` or later get a short `content` text plus the full result once in `structuredContent`; earlier or missing revisions get the full JSON in `content`. Set `compat` to always send the full JSON in `content`, or `compact` to always send the short form. The meta-tools always return their result in `content`. See [docs/configuration.md](docs/configuration.md#mcp-response-content).

### One cloud credential, kept apart from console credentials

This server has one credential: the Site Manager API key. There is no console host, username, password or local API key, and no second authentication path.

The key is read only from `UNIFI_SITEMANAGER_API_KEY` or its `_FILE` / `_COMMAND` forms. It is never read from:

- `UNIFI_API_KEY` or any other shared `UNIFI_*` variable. Those hold a console's local credentials, which must never be sent to the cloud, and a Site Manager key must never reach a console.
- `config.yaml` or a `CONFIG_PATH` file.

The separation runs both ways because the two keys reach different places. A console key opens one console on your network. A Site Manager key reads every console on the account from anywhere on the internet.

## Secret redaction

Responses pass through the same redaction as the other servers: fields whose names mark them as secrets come back as `***REDACTED***`. Set `UNIFI_SITEMANAGER_REDACT_SENSITIVE_FIELDS=false` (or the shared `UNIFI_REDACT_SENSITIVE_FIELDS=false`) only for a trusted local process that needs raw values. Independently of that setting, the account holder's name, email and role are never returned. See [docs/permissions.md](docs/permissions.md#response-redaction).

## Run

Stdio is the default transport, for Claude Desktop, Claude Code and other local clients:

```bash
uv run --package unifi-sitemanager-mcp unifi-sitemanager-mcp
```

HTTP is opt-in and listens on port 3003 by default. It is meant for a container, where the server is the main process; the [Docker Compose](#docker-compose) service below turns it on. Outside a container the server skips HTTP unless `UNIFI_MCP_HTTP_FORCE=true` is also set, which is for local testing only:

```bash
UNIFI_MCP_HTTP_ENABLED=true UNIFI_MCP_HTTP_FORCE=true \
UNIFI_SITEMANAGER_MCP_HTTP_AUTH_TOKEN_FILE="$HOME/.config/unifi-mcp/sitemanager-http-token" \
uv run --package unifi-sitemanager-mcp unifi-sitemanager-mcp
```

Never set these variables in a client's MCP entry. Anyone who can reach the HTTP endpoint can read the whole account's inventory. Keep it on loopback, the default bind address, and set a bearer token. See [HTTP transport](docs/configuration.md#http-transport).

### Docker Compose

The Compose file builds the image from this checkout. The Site Manager service is in the opt-in `sitemanager` profile, so it does not start with the other servers:

```bash
export UNIFI_SITEMANAGER_API_KEY="$(cat "$HOME/.config/unifi-mcp/sitemanager-api-key")"
docker compose -f docker/docker-compose.yml --profile sitemanager up --build unifi-sitemanager-mcp
```

The key is taken from your shell when the container starts and is never built into the image. The service receives only its own key variables, never the shared env file or console logins, and serves HTTP on `127.0.0.1:3003`. To use `UNIFI_SITEMANAGER_API_KEY_FILE` instead, mount the secret read-only and give its path inside the container; `UNIFI_SITEMANAGER_API_KEY_COMMAND` must name a helper installed in the image.

### Claude Desktop

Add to `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "unifi-sitemanager": {
      "command": "uvx",
      "args": ["unifi-sitemanager-mcp@latest"],
      "env": {
        "UNIFI_SITEMANAGER_API_KEY_FILE": "/Users/you/.config/unifi-mcp/sitemanager-api-key"
      }
    }
  }
}
```

Use a file or command provider rather than putting the key itself in the config file.

## Remote access

The server can be listed in a relay's `UNIFI_RELAY_SERVERS` like the others, but it is not added by default. Relay tokens are scoped to a location, and this server exposes the whole account: anyone holding a token for that location, including a read-only one, could then read the inventory of every console on the account.

## Features

Nine read-only tools. See [docs/tools.md](docs/tools.md).

| Tool | What it returns |
|---|---|
| `sitemanager_list_hosts` | Consoles and self-hosted servers on the account |
| `sitemanager_get_host` | One host, optionally with its full reported state |
| `sitemanager_list_sites` | Sites across every host, with counts and WAN health |
| `sitemanager_list_devices` | Devices grouped by host, with firmware status |
| `sitemanager_get_isp_metrics` | WAN performance for every site |
| `sitemanager_query_isp_metrics` | WAN performance for named sites |
| `sitemanager_list_sdwan_configs` | SD-WAN configurations |
| `sitemanager_get_sdwan_config` | One SD-WAN configuration |
| `sitemanager_get_sdwan_config_status` | Deployment status of one SD-WAN configuration |

Host, site and device ids returned here belong to the Site Manager tool family. They are not the ids the Network, Protect or Access servers use, and there is no translation between them.

**Supported:** reading hosts, sites, devices, ISP metrics and SD-WAN configurations for the account behind the key, one page at a time.

**Not supported:** any write or configuration change, firmware updates, reboots, events or real-time streams, MCP resources, support bundles, and reading data from inside a console (clients, firewall rules, cameras, doors). For those, use the Network, Protect or Access server against the console itself.

### Limits

- The API allows 10,000 requests per minute. When it answers 429 the server waits briefly for a read, then reports the retry time.
- A personal API key lists consoles the account owns or has been invited to.
- List tools return one page at a time and never crawl every page on their own.

## Documentation

- [Configuration](docs/configuration.md): the API key, settings, HTTP transport, diagnostics, tracing, registration modes
- [Permissions](docs/permissions.md): why there is nothing to gate, what controls access instead, response redaction
- [Tool catalog](docs/tools.md): the nine tools with argument examples and response shapes
- [Troubleshooting](docs/troubleshooting.md): key, network, missing tools, Docker and logging problems
- [Credential providers](../../docs/credential-providers.md): the `_FILE` and `_COMMAND` contract
- [MCP discovery and meta-tools](../../docs/tool-index.md): `tools/list`, `sitemanager_tool_index` and `sitemanager_execute`

The same nine reads are also available through [`unifi-api-server`](../api/).

## Development

```bash
cd apps/sitemanager
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
