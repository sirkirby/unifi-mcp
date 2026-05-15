# Configuration

The UniFi Access MCP server merges settings from three sources (highest priority first):

1. **Environment variables** (or `.env` file)
2. **YAML config file** (`src/unifi_access_mcp/config/config.yaml`)
3. **Hardcoded defaults**

## Essential Variables

The Access server supports server-specific environment variables with the `UNIFI_ACCESS_` prefix. These take priority over the shared `UNIFI_*` variables, which serve as a fallback. For single-controller setups, the shared variables are all you need.

| Server-specific variable | Shared fallback | Required | Default | Description |
|--------------------------|-----------------|----------|---------|-------------|
| `UNIFI_ACCESS_HOST` | `UNIFI_HOST` | Yes | -- | Controller IP or hostname |
| `UNIFI_ACCESS_USERNAME` | `UNIFI_USERNAME` | Yes* | -- | Local admin username (*required for proxy path) |
| `UNIFI_ACCESS_PASSWORD` | `UNIFI_PASSWORD` | Yes* | -- | Admin password (*required for proxy path) |
| `UNIFI_ACCESS_PORT` | `UNIFI_PORT` | No | `443` | Controller HTTPS port (UniFi OS Console) |
| `UNIFI_ACCESS_VERIFY_SSL` | `UNIFI_VERIFY_SSL` | No | `false` | SSL certificate verification |
| `UNIFI_ACCESS_API_KEY` | `UNIFI_API_KEY` | No | `""` | Official UniFi API key (for API-key auth path) |

**Resolution order:** `UNIFI_ACCESS_*` > `UNIFI_*` > YAML config > hardcoded default.

## Dual-Path Authentication

The Access server has two independent auth paths. At least one must be configured.

### Path 1: API Key (port 12445)

Uses the `py-unifi-access` library to connect to the dedicated Access API port. Best for read-only queries and device listing.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_ACCESS_API_KEY` | `""` | API key obtained from the UniFi OS Console |
| `UNIFI_ACCESS_API_PORT` | `12445` | Dedicated Access API port (used by `py-unifi-access`) |

### Path 2: Local Proxy Session (port 443)

Logs in via `/api/auth/login` on the UniFi OS Console and proxies requests through `/proxy/access/api/v2/...` with cookie + CSRF token. Required for most mutating operations.

| Variable | Required | Description |
|----------|----------|-------------|
| `UNIFI_ACCESS_USERNAME` | Yes | Local admin username |
| `UNIFI_ACCESS_PASSWORD` | Yes | Admin password |
| `UNIFI_ACCESS_PORT` | No (443) | UniFi OS Console HTTPS port |

When both paths are available, each tool selects the most appropriate one. Most mutating tools (door lock/unlock, credential management, policies, visitors, events) require the local proxy session. See the `auth` metadata on each tool for which path it uses.

## Server Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_LOG_LEVEL` | `INFO` | Logging level |
| `UNIFI_AUTO_CONFIRM` | `false` | Skip preview-then-confirm for mutations (for automation) |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | Tool loading: `lazy`, `eager`, or `meta_only` |
| `UNIFI_ENABLED_CATEGORIES` | -- | Comma-separated tool categories to load (eager mode only) |
| `UNIFI_ENABLED_TOOLS` | -- | Comma-separated tool names to register (eager mode only) |
| `CONFIG_PATH` | -- | Path to a custom config YAML file |

## Access-Specific Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_ACCESS_API_PORT` | `12445` | Port for the py-unifi-access API (API key auth path) |
| `ACCESS_EVENT_BUFFER_SIZE` | `100` | Max events held in the websocket ring buffer |
| `ACCESS_EVENT_BUFFER_TTL` | `300` | Seconds before buffered events expire (lazy eviction) |
| `ACCESS_WEBSOCKET_ENABLED` | `true` | Enable real-time event websocket listener |

## HTTP Transport

HTTP is disabled by default. The stdio transport is recommended for most MCP clients.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_HTTP_ENABLED` | `false` | Enable HTTP transport |
| `UNIFI_MCP_HTTP_TRANSPORT` | `streamable-http` | `streamable-http` (recommended) or `sse` (legacy) |
| `UNIFI_MCP_HOST` | `0.0.0.0` | HTTP bind address |
| `UNIFI_MCP_PORT` | `3002` | HTTP bind port |
| `UNIFI_MCP_HTTP_FORCE` | `false` | Force HTTP in non-container environments |

**Note:** The Access server defaults to port 3002 (vs. 3000 for Network, 3001 for Protect) to allow running all servers simultaneously.

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
| `UNIFI_ACCESS_TOOL_PERMISSION_MODE` / `UNIFI_TOOL_PERMISSION_MODE` | `confirm` | `confirm` (preview-then-confirm flow) or `bypass` (skip confirmations) |

Policy gates follow the pattern `UNIFI_POLICY_ACCESS_<CATEGORY>_<ACTION>` (most specific) down to `UNIFI_POLICY_<ACTION>` (global). Most specific wins.

Examples:
```bash
UNIFI_POLICY_ACCESS_DOORS_UPDATE=true
UNIFI_POLICY_ACCESS_CREDENTIALS_CREATE=true
UNIFI_POLICY_ACCESS_VISITORS_DELETE=true
# Or server-wide:
UNIFI_POLICY_ACCESS_UPDATE=true
```

## Tool Categories

Valid values for `UNIFI_ENABLED_CATEGORIES` (eager mode):

| Category | Description |
|----------|-------------|
| `doors` | Door listing, lock/unlock, status, groups |
| `policies` | Access policies and schedules |
| `credentials` | NFC cards, PINs, mobile credentials |
| `visitors` | Visitor pass management |
| `events` | Access events, activity summaries, real-time buffer |
| `devices` | Access hubs, readers, relays, intercoms |
| `system` | Controller info, health, user listing |

## Tool Registration Modes

Standard MCP clients discover currently registered tools with `tools/list`.
UniFi meta-tools are compatibility extensions for lazy loading and compact
catalog discovery. See [MCP Discovery and UniFi Meta-Tools](../../../docs/tool-index.md).

| Mode | Initial `tools/list` behavior | Best fit |
|------|-------------------------------|----------|
| `lazy` (default) | Meta-tools plus `access_load_tools`; domain tools load on demand | Production LLM clients with limited context |
| `eager` | Meta-tools plus all selected Access tools registered directly | Standard MCP clients and dev consoles |
| `meta_only` | Core meta-tools only; use `access_execute` for operations | Maximum context control |

## YAML Config Reference

The full config file lives at `src/unifi_access_mcp/config/config.yaml`. All values use OmegaConf interpolation so environment variables take precedence:

```yaml
unifi:
  host: ${oc.env:UNIFI_ACCESS_HOST,""}
  username: ${oc.env:UNIFI_ACCESS_USERNAME,""}
  password: ${oc.env:UNIFI_ACCESS_PASSWORD,""}
  port: ${oc.env:UNIFI_ACCESS_PORT,443}
  site: ${oc.env:UNIFI_ACCESS_SITE,default}
  verify_ssl: ${oc.env:UNIFI_ACCESS_VERIFY_SSL,false}
  api_key: ${oc.env:UNIFI_ACCESS_API_KEY,""}

server:
  host: ${oc.env:UNIFI_MCP_HOST,0.0.0.0}
  port: ${oc.env:UNIFI_MCP_PORT,3002}
  log_level: INFO
  tool_registration_mode: ${oc.env:UNIFI_TOOL_REGISTRATION_MODE,lazy}

access:
  api_port: ${oc.env:UNIFI_ACCESS_API_PORT,12445}
  events:
    buffer_size: ${oc.env:ACCESS_EVENT_BUFFER_SIZE,100}
    buffer_ttl_seconds: ${oc.env:ACCESS_EVENT_BUFFER_TTL,300}
    websocket_enabled: ${oc.env:ACCESS_WEBSOCKET_ENABLED,true}

permissions:
  default:
    create: false
    update: false
    delete: false
```

You can override the config file location with `CONFIG_PATH=/path/to/config.yaml`.
