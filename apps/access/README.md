<!-- mcp-name: io.github.sirkirby/unifi-access-mcp -->
# UniFi Access MCP Server

<p align="center">
  <img src="../../assets/hero-access.svg" alt="UniFi Access MCP Server" width="720">
</p>

MCP server exposing UniFi Access tools for LLMs, agents, and automation platforms. Manage doors, credentials, access policies, visitors, events, and devices -- with safe-by-default permissions and preview-before-confirm for all mutations.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)

## Install

### Claude Code (recommended)

The plugin installs the MCP server, an agent skill for tool discovery, and a guided setup command:

```
/plugin marketplace add sirkirby/unifi-mcp
/plugin install unifi-access@unifi-plugins
```

Then run the interactive setup to configure your controller connection:

```
/unifi-access:setup
```

This walks you through connecting to your Access controller, explains the dual-auth system (API key for reads, username/password for mutations), and configures permissions — then writes everything to `.claude/settings.local.json`. If you already have other UniFi plugins configured on the same controller, the setup will detect and reuse those credentials. Restart Claude Code after setup to connect.

### Codex

Register the marketplace, then install `unifi-access` from Codex's `/plugins` UI:

```bash
codex plugin marketplace add sirkirby/unifi-mcp
```

After installing, ask Codex to use the UniFi Access setup skill. The setup flow registers the MCP server with `codex mcp add`, stores your controller environment values in Codex's MCP configuration, and prompts you to restart Codex.

### PyPI / Docker

```bash
# PyPI
uvx unifi-access-mcp@latest
# or: pip install unifi-access-mcp

# Docker
docker pull ghcr.io/sirkirby/unifi-access-mcp:latest

# From source
git clone https://github.com/sirkirby/unifi-mcp.git
cd unifi-mcp && uv sync
```

## Usage Examples

Once connected, just ask your AI agent in natural language:

> "Who badged into the office today? Show me a timeline of all door access events"

> "List all access credentials that expire in the next 30 days"

> "Show me failed badge attempts at the server room this week — any patterns?"

> "Which doors had the most access events today?"

> "Create a visitor pass for John Smith with access to the main entrance from 9 AM to 5 PM tomorrow"

> "Audit door policies — which doors allow access outside business hours?"

All queries are read-only by default. Mutations (visitor passes, credential changes, door controls) use a **preview-then-confirm** flow.

## Configure

Set these environment variables (or create a `.env` file). If you used `/unifi-access:setup`, this is already done.

```bash
# Server-specific variables (recommended)
UNIFI_ACCESS_HOST=192.168.1.1      # Controller IP or hostname
UNIFI_ACCESS_USERNAME=admin         # Local admin username
UNIFI_ACCESS_PASSWORD=your-password # Admin password
# Optional:
# UNIFI_ACCESS_API_KEY=             # Official UniFi API key (dual auth)
# UNIFI_ACCESS_PORT=443             # Controller HTTPS port
# UNIFI_ACCESS_VERIFY_SSL=false     # SSL certificate verification
```

**Fallback:** The shared `UNIFI_*` variables (e.g., `UNIFI_HOST`) also work. The server checks for `UNIFI_ACCESS_*` first and falls back to `UNIFI_*` if the server-specific variable is not set. For single-controller setups, the shared variables are all you need.

### Dual Authentication

The Access server supports two independent auth paths:

1. **API key** -- Uses `py-unifi-access` on the dedicated Access API port (default 12445). Best for read-only queries and device listing.
2. **Local proxy session** -- Logs in via `/api/auth/login` on the UniFi OS Console (port 443) and proxies requests through `/proxy/access/api/v2/...`. Required for door lock/unlock, credential management, policies, visitors, and events.

At least one path must be configured. When both are available, each tool selects the most appropriate path. Most mutating tools require the local proxy session.

## Run

```bash
# stdio transport (default -- for Claude Desktop, LM Studio, etc.)
unifi-access-mcp

# Docker
docker run -i --rm \
  -e UNIFI_ACCESS_HOST=192.168.1.1 \
  -e UNIFI_ACCESS_USERNAME=admin \
  -e UNIFI_ACCESS_PASSWORD=secret \
  ghcr.io/sirkirby/unifi-access-mcp:latest
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "unifi-access": {
      "command": "uvx",
      "args": ["unifi-access-mcp"],
      "env": {
        "UNIFI_ACCESS_HOST": "192.168.1.1",
        "UNIFI_ACCESS_USERNAME": "admin",
        "UNIFI_ACCESS_PASSWORD": "your-password"
      }
    }
  }
}
```

## Features

- **Doors** -- list, inspect, lock/unlock, door groups, real-time status
- **Policies** -- list, inspect, update access policies and schedules
- **Credentials** -- list, inspect, create, revoke NFC cards, PINs, mobile credentials
- **Visitors** -- list, inspect, create, delete visitor passes with time-bounded access
- **Events** -- query historical events, real-time websocket buffer, activity summaries
- **Devices** -- list, inspect, reboot access hubs, readers, relays, intercoms
- **System** -- controller info, health metrics, user listing

## Agent Skills

The Claude Code plugin ships with agent skills that teach AI assistants how to work with Access effectively:

- **UniFi Access** — core skill for door control, credentials, visitors, access policies, and event monitoring. Includes guidance on the dual-auth system, real-time event streaming via WebSocket buffer, and the preview-confirm flow for physical door operations.
- **Setup** — interactive configuration wizard that walks through controller connection, credential setup, and permission configuration.

Skills are automatically available when the plugin is installed.

## Cross-Product Skills

When the Access plugin is installed alongside the **Protect plugin**, the `security-digest` skill can incorporate door events into its analysis. Badge-ins, access-denied events, and after-hours access are correlated with camera motion and alerts from Protect to produce a richer security summary across your full UniFi deployment.

No additional configuration is required — if both plugins are active, the skill automatically pulls from both servers.

## Documentation

- [Configuration](docs/configuration.md) -- Full env var reference, YAML config, Access-specific options
- [Permissions](docs/permissions.md) -- Permission system, category defaults, how to enable mutations
- [Tool Catalog](docs/tools.md) -- All 29 tools organized by category
- [Event Streaming](docs/events.md) -- Real-time event architecture, WebSocket buffer, polling
- [Troubleshooting](docs/troubleshooting.md) -- Connection issues, dual auth debugging, missing tools

## Development

```bash
cd apps/access
make test         # Run tests
make lint         # Lint
make format       # Format
make manifest     # Regenerate tools_manifest.json
make console      # Start interactive dev console
make pre-commit   # All of the above
```

See the root [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full monorepo workflow.

## License

[MIT](../../LICENSE)
