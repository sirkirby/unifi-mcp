# Configuration

The UniFi Protect MCP server merges settings from three sources (highest priority first):

1. **Environment variables** (or `.env` file)
2. **YAML config file** (`src/unifi_protect_mcp/config/config.yaml`)
3. **Hardcoded defaults**

## Essential Variables

The Protect server supports server-specific environment variables with the `UNIFI_PROTECT_` prefix. These take priority over the shared `UNIFI_*` variables, which serve as a fallback. For single-controller setups, the shared variables are all you need.

| Server-specific variable | Shared fallback | Required | Default | Description |
|--------------------------|-----------------|----------|---------|-------------|
| `UNIFI_PROTECT_HOST` | `UNIFI_HOST` | Yes | -- | Controller IP or hostname |
| `UNIFI_PROTECT_USERNAME` | `UNIFI_USERNAME` | Yes | -- | Local admin username |
| `UNIFI_PROTECT_PASSWORD` | `UNIFI_PASSWORD` | Yes | -- | Admin password |
| `UNIFI_PROTECT_PORT` | `UNIFI_PORT` | No | `443` | Controller HTTPS port |
| `UNIFI_PROTECT_VERIFY_SSL` | `UNIFI_VERIFY_SSL` | No | `false` | SSL certificate verification |
| `UNIFI_PROTECT_API_KEY` | `UNIFI_API_KEY` | No | `""` | UniFi API key (experimental — read-only, subset of tools; username/password still required) |

**Resolution order:** `UNIFI_PROTECT_*` > `UNIFI_*` > YAML config > hardcoded default.

## Server Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_LOG_LEVEL` | `INFO` | Logging level |
| `UNIFI_AUTO_CONFIRM` | `false` | Skip preview-then-confirm for mutations (for automation) |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | Tool loading: `lazy`, `eager`, or `meta_only` |
| `UNIFI_ENABLED_CATEGORIES` | -- | Comma-separated tool categories to load (eager mode only) |
| `UNIFI_ENABLED_TOOLS` | -- | Comma-separated tool names to register (eager mode only) |
| `CONFIG_PATH` | -- | Path to a custom config YAML file |

## Protect-Specific Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PROTECT_EVENT_BUFFER_SIZE` | `100` | Max events held in the websocket ring buffer |
| `PROTECT_EVENT_BUFFER_TTL` | `300` | Seconds before buffered events expire (lazy eviction) |
| `PROTECT_WEBSOCKET_ENABLED` | `true` | Enable real-time event websocket listener |
| `PROTECT_SMART_DETECTION_MIN_CONFIDENCE` | `50` | Minimum confidence score (0-100) for smart detection queries |

## HTTP Transport

HTTP is disabled by default. The stdio transport is recommended for most MCP clients.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_HTTP_ENABLED` | `false` | Enable HTTP transport |
| `UNIFI_MCP_HTTP_TRANSPORT` | `streamable-http` | `streamable-http` (recommended) or `sse` (legacy) |
| `UNIFI_MCP_HOST` | `0.0.0.0` | HTTP bind address |
| `UNIFI_MCP_PORT` | `3001` | HTTP bind port |
| `UNIFI_MCP_HTTP_FORCE` | `false` | Force HTTP in non-container environments |

**Note:** The Protect server defaults to port 3001 (vs. 3000 for the Network server) to allow running both servers simultaneously.

## Diagnostics

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_DIAGNOSTICS` | `false` | Enable structured logging for tool calls and API requests |
| `UNIFI_MCP_DIAG_LOG_TOOL_ARGS` | `true` | Include tool arguments in diagnostic logs |
| `UNIFI_MCP_DIAG_LOG_TOOL_RESULT` | `true` | Include tool results in diagnostic logs |
| `UNIFI_MCP_DIAG_MAX_PAYLOAD` | `2000` | Max characters for diagnostic payloads |

## Permissions

Authorization is enforced at call time. All tools remain visible regardless of permission configuration. See [permissions.md](permissions.md) for full details.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_PROTECT_TOOL_PERMISSION_MODE` / `UNIFI_TOOL_PERMISSION_MODE` | `confirm` | `confirm` (preview-then-confirm flow) or `bypass` (skip confirmations) |

Policy gates follow the pattern `UNIFI_POLICY_PROTECT_<CATEGORY>_<ACTION>` (most specific) down to `UNIFI_POLICY_<ACTION>` (global). Most specific wins.

Examples:
```bash
UNIFI_POLICY_PROTECT_CAMERAS_UPDATE=true
UNIFI_POLICY_PROTECT_CHIMES_UPDATE=true
UNIFI_POLICY_PROTECT_LIGHTS_UPDATE=true
# Or server-wide:
UNIFI_POLICY_PROTECT_UPDATE=true
```

## Tool Categories

Valid values for `UNIFI_ENABLED_CATEGORIES` (eager mode):

| Category | Description |
|----------|-------------|
| `cameras` | Camera listing, snapshots, streams, PTZ, settings |
| `events` | Motion events, smart detections, thumbnails |
| `recordings` | Recording status, availability, clip export |
| `devices` | Lights, sensors, chimes |
| `liveviews` | Multi-camera layout management |
| `system` | NVR info, health, firmware, viewers |

## Tool Registration Modes

Standard MCP clients discover currently registered tools with `tools/list`.
UniFi meta-tools are compatibility extensions for lazy loading and compact
catalog discovery. See [MCP Discovery and UniFi Meta-Tools](../../../docs/tool-index.md).

| Mode | Initial `tools/list` behavior | Best fit |
|------|-------------------------------|----------|
| `lazy` (default) | Meta-tools plus `protect_load_tools`; domain tools load on demand | Production LLM clients with limited context |
| `eager` | Meta-tools plus all selected Protect tools registered directly | Standard MCP clients and dev consoles |
| `meta_only` | Core meta-tools only; use `protect_execute` for operations | Maximum context control |

## YAML Config Reference

The full config file lives at `src/unifi_protect_mcp/config/config.yaml`. All values use OmegaConf interpolation so environment variables take precedence:

```yaml
unifi:
  host: ${oc.env:UNIFI_HOST,""}
  username: ${oc.env:UNIFI_USERNAME,""}
  password: ${oc.env:UNIFI_PASSWORD,""}
  port: ${oc.env:UNIFI_PORT,443}
  site: ${oc.env:UNIFI_SITE,default}
  verify_ssl: ${oc.env:UNIFI_VERIFY_SSL,false}

server:
  host: ${oc.env:UNIFI_MCP_HOST,0.0.0.0}
  port: ${oc.env:UNIFI_MCP_PORT,3001}
  log_level: INFO
  tool_registration_mode: ${oc.env:UNIFI_TOOL_REGISTRATION_MODE,lazy}

protect:
  events:
    buffer_size: ${oc.env:PROTECT_EVENT_BUFFER_SIZE,100}
    buffer_ttl_seconds: ${oc.env:PROTECT_EVENT_BUFFER_TTL,300}
    websocket_enabled: ${oc.env:PROTECT_WEBSOCKET_ENABLED,true}
    smart_detection_min_confidence: ${oc.env:PROTECT_SMART_DETECTION_MIN_CONFIDENCE,50}

permissions:
  default:
    create: false
    update: false
    delete: false
```

You can override the config file location with `CONFIG_PATH=/path/to/config.yaml`.
