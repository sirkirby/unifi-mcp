<!-- mcp-name: io.github.sirkirby/unifi-protect-mcp -->
# UniFi Protect MCP Server

<p align="center">
  <img src="../../assets/hero-protect.svg" alt="UniFi Protect MCP Server" width="720">
</p>

MCP server exposing UniFi Protect tools for LLMs, agents, and automation platforms. Query cameras, events, smart detections, Find Anything detection search, recordings, lights, sensors, chimes, Known Faces, license plates, and the Alarm Manager -- with safe-by-default permissions and preview-before-confirm for all mutations.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)

## Install

### Claude Code (recommended)

The plugin installs the MCP server, an agent skill for tool discovery, and a guided setup command:

```
/plugin marketplace add sirkirby/unifi-mcp
/plugin install unifi-protect@unifi-plugins
```

Then run the interactive setup to configure your controller connection:

```
/unifi-protect:setup
```

This walks you through entering your controller host, credentials, and permission preferences — then writes everything to `.claude/settings.local.json` so it persists across sessions. If you already have the Network plugin configured on the same controller, the setup will detect and reuse those credentials. Restart Claude Code after setup to connect.

### Codex

Register the marketplace, then install `unifi-protect` from Codex's `/plugins` UI:

```bash
codex plugin marketplace add sirkirby/unifi-mcp
```

After installing, ask Codex to use the UniFi Protect setup skill. The setup flow registers the MCP server with `codex mcp add`, stores your controller environment values in Codex's MCP configuration, and prompts you to restart Codex.

### PyPI / Docker

```bash
# PyPI
uvx unifi-protect-mcp@latest
# or: pip install unifi-protect-mcp

# Docker
docker pull ghcr.io/sirkirby/unifi-protect-mcp:latest

# From source
git clone https://github.com/sirkirby/unifi-mcp.git
cd unifi-mcp && uv sync
```

## Usage Examples

Once connected, just ask your AI agent in natural language:

> "List all cameras that detected motion in the last hour"

> "Show me smart detection events from the front door camera today — people and vehicles only"

> "Find driveway detections for white vans this week"

> "Which cameras have the most motion events this week? Any unusual patterns?"

> "Are there any cameras offline or with degraded connections?"

> "Show me all recording events from the driveway camera between 2 AM and 5 AM last night"

> "What sensors triggered alerts today and what were the readings?"

All camera and event queries are read-only by default. Mutations (camera settings, light controls) use a **preview-then-confirm** flow.

## Configure

Set these environment variables (or create a `.env` file). If you used `/unifi-protect:setup`, this is already done.

```bash
# Server-specific variables (recommended)
UNIFI_PROTECT_HOST=192.168.1.1      # Controller IP or hostname
UNIFI_PROTECT_USERNAME=admin         # Local admin username
UNIFI_PROTECT_PASSWORD=your-password # Admin password
# Optional:
# UNIFI_PROTECT_API_KEY=             # UniFi API key (experimental — read-only, subset of tools)
# UNIFI_PROTECT_PORT=443             # Controller HTTPS port
# UNIFI_PROTECT_VERIFY_SSL=false     # SSL certificate verification
```

**Fallback:** The shared `UNIFI_*` variables (e.g., `UNIFI_HOST`) also work. The server checks for `UNIFI_PROTECT_*` first and falls back to `UNIFI_*` if the server-specific variable is not set. For single-controller setups, the shared variables are all you need.

> **AI-powered alarms need SuperAdmin.** The alarm-rule tools (`protect_alarm_list_rules` / `protect_alarm_get_rule`) transparently surface AI-powered alarms (e.g. AI Natural Language) from the modern UniFi-OS Alarm Manager when the account is **SuperAdmin**, and fall back to the classic automations view otherwise. With a non-SuperAdmin account those AI alarms aren't visible and the response includes a standard MCP `_meta` notice saying so. Grant the account SuperAdmin on the console hosting Protect to view/manage them. Blast radius: on a standalone UNVR this is contained to Protect; on a combined UDM console SuperAdmin also grants Network/UniFi-OS control.

## Run

```bash
# stdio transport (default -- for Claude Desktop, LM Studio, etc.)
unifi-protect-mcp

# Docker
docker run -i --rm \
  -e UNIFI_PROTECT_HOST=192.168.1.1 \
  -e UNIFI_PROTECT_USERNAME=admin \
  -e UNIFI_PROTECT_PASSWORD=secret \
  ghcr.io/sirkirby/unifi-protect-mcp:latest
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "unifi-protect": {
      "command": "uvx",
      "args": ["unifi-protect-mcp"],
      "env": {
        "UNIFI_PROTECT_HOST": "192.168.1.1",
        "UNIFI_PROTECT_USERNAME": "admin",
        "UNIFI_PROTECT_PASSWORD": "your-password"
      }
    }
  }
}
```

## Features

- **Cameras** -- list, inspect, snapshot, RTSP streams, PTZ control, settings, recording toggle, reboot
- **Events** -- query historical events, smart detections (person/vehicle/animal/package), Find Anything detection search, thumbnails
- **Real-time streaming** -- websocket event buffer with MCP resource subscriptions and polling
- **Recordings** -- status, availability, clip export with timelapse support
- **Known Faces** -- list, rename, merge, and remove face recognition groups
- **Devices** -- lights (brightness, PIR sensitivity), sensors (temperature, humidity, motion), chimes (volume, trigger)
- **Liveviews** -- list and inspect multi-camera layouts
- **System** -- NVR info, health metrics, firmware status, connected viewers

## Agent Skills

The Protect plugin ships one agent skill that works alongside the MCP tools:

### Security Digest

Cross-product event intelligence that generates a concise security summary across all connected UniFi systems.

- **Sources:** Protect camera events, Access door events, Network firewall activity
- **Severity classification:** Events are classified by time-of-day context (business hours vs. after hours vs. overnight) and event type (person detection, vehicle, door access, firewall block, etc.)
- **Cross-product correlation:** Five built-in correlation rules surface patterns that span products:
  - Motion at a door camera without a corresponding badge-in
  - Multiple failed door access attempts in a short window
  - Person detection coinciding with firewall blocks from the same timeframe
  - After-hours camera activity with no Access event
  - Repeated vehicle detections at the perimeter
- **Activity counts:** Aggregated totals across all sources for quick at-a-glance awareness

Invoke via the skill command after installing the plugin:

```
/unifi-protect:security-digest
```

## Event Improvements

### camera_name in Event Responses

All event-related tools now include `camera_name` alongside `camera_id` in every event object. The name is resolved from bootstrap data cached at startup — no extra API calls required.

Affected tools: `protect_list_events`, `protect_list_smart_detections`, `protect_recent_events`

Before:
```json
{ "camera_id": "abc123", "type": "motion", ... }
```

After:
```json
{ "camera_id": "abc123", "camera_name": "Front Door", "type": "motion", ... }
```

This eliminates the need to call `protect_list_cameras` separately just to map IDs to names.

### Compact Mode

`protect_list_events` and `protect_list_smart_detections` accept a `compact=true` parameter that strips low-signal fields from responses: `thumbnail_id`, `category`, `sub_category`, and `is_favorite`. This produces responses roughly 40% smaller.

```python
# Standard call
protect_list_events(limit=50)

# Compact — recommended for digests, summaries, and context-constrained workflows
protect_list_events(limit=50, compact=True)
```

Compact mode is the recommended default when building summaries or feeding events into downstream prompts where token budget matters.

## Documentation

- [Configuration](docs/configuration.md) -- Full env var reference, YAML config, Protect-specific options
- [Permissions](docs/permissions.md) -- Permission system, category defaults, how to enable mutations
- [Tool Catalog](docs/tools.md) -- All 58 tools organized by category
- [Event Streaming](docs/events.md) -- Real-time event architecture, MCP resources, polling
- [Troubleshooting](docs/troubleshooting.md) -- Connection issues, SSL, missing tools

## Development

```bash
cd apps/protect
make test         # Run tests
make lint         # Lint
make format       # Format
make manifest     # Regenerate tools_manifest.json
make pre-commit   # All of the above
```

See the root [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full monorepo workflow.

## License

[MIT](../../LICENSE)
