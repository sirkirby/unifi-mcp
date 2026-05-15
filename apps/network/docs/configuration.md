# Configuration

The UniFi Network MCP server merges settings from three sources (highest priority first):

1. **Environment variables** (or `.env` file)
2. **YAML config file** (`src/unifi_network_mcp/config/config.yaml`)
3. **Hardcoded defaults**

## Essential Variables

The Network server supports server-specific environment variables with the `UNIFI_NETWORK_` prefix. These take priority over the shared `UNIFI_*` variables, which serve as a fallback. For single-controller setups, the shared variables are all you need.

| Server-specific variable | Shared fallback | Required | Default | Description |
|--------------------------|-----------------|----------|---------|-------------|
| `UNIFI_NETWORK_HOST` | `UNIFI_HOST` | Yes | -- | Controller IP or hostname |
| `UNIFI_NETWORK_USERNAME` | `UNIFI_USERNAME` | Yes | -- | Local admin username |
| `UNIFI_NETWORK_PASSWORD` | `UNIFI_PASSWORD` | Yes | -- | Admin password |
| `UNIFI_NETWORK_API_KEY` | `UNIFI_API_KEY` | No | `""` | UniFi API key (experimental — read-only, subset of tools; username/password still required) |
| `UNIFI_NETWORK_PORT` | `UNIFI_PORT` | No | `443` | Controller HTTPS port |
| `UNIFI_NETWORK_SITE` | `UNIFI_SITE` | No | `default` | UniFi site name |
| `UNIFI_NETWORK_VERIFY_SSL` | `UNIFI_VERIFY_SSL` | No | `false` | SSL certificate verification |

**Resolution order:** `UNIFI_NETWORK_*` > `UNIFI_*` > YAML config > hardcoded default.

## Controller Type Detection

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_NETWORK_CONTROLLER_TYPE` / `UNIFI_CONTROLLER_TYPE` | `auto` | API path detection: `auto`, `proxy` (UniFi OS), `direct` (standalone) |

The server auto-detects whether your controller uses UniFi OS proxy paths (`/proxy/network/api/...`) or direct paths (`/api/...`). This adds ~300ms to the initial connection.

**Manual override** — use when auto-detection fails or you want faster startup:
- `proxy` — UniFi OS controllers (Cloud Gateway, UDM-Pro, UniFi OS 4.x+)
- `direct` — Standalone UniFi Network controllers

## Server Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_LOG_LEVEL` | `INFO` | Logging level |
| `UNIFI_AUTO_CONFIRM` | `false` | Skip preview-then-confirm for mutations (for automation) |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | Tool loading: `lazy`, `eager`, or `meta_only` |
| `UNIFI_ENABLED_CATEGORIES` | — | Comma-separated tool categories to load (eager mode only) |
| `UNIFI_ENABLED_TOOLS` | — | Comma-separated tool names to register (eager mode only) |
| `CONFIG_PATH` | — | Path to a custom config YAML file |

## Tool Registration Modes

Standard MCP clients discover currently registered tools with `tools/list`.
UniFi meta-tools are compatibility extensions for lazy loading and compact
catalog discovery. See [MCP Discovery and UniFi Meta-Tools](../../../docs/tool-index.md).

| Mode | Initial `tools/list` behavior | Best fit |
|------|-------------------------------|----------|
| `lazy` (default) | Meta-tools plus `unifi_load_tools`; domain tools load on demand | Production LLM clients with limited context |
| `eager` | Meta-tools plus all selected Network tools registered directly | Standard MCP clients and dev consoles |
| `meta_only` | Core meta-tools only; use `unifi_execute` for operations | Maximum context control |

## HTTP Transport

HTTP is disabled by default. The stdio transport is recommended for most use cases.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_HTTP_ENABLED` | `false` | Enable HTTP transport |
| `UNIFI_MCP_HTTP_TRANSPORT` | `streamable-http` | `streamable-http` (recommended) or `sse` (legacy) |
| `UNIFI_MCP_HOST` | `0.0.0.0` | HTTP bind address |
| `UNIFI_MCP_PORT` | `3000` | HTTP bind port |
| `UNIFI_MCP_HTTP_FORCE` | `false` | Force HTTP in non-container environments |

## Security

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Allowed hostnames (for reverse proxy setups) |
| `UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION` | `true` | DNS rebinding protection |

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
| `UNIFI_NETWORK_TOOL_PERMISSION_MODE` / `UNIFI_TOOL_PERMISSION_MODE` | `confirm` | `confirm` (preview-then-confirm flow) or `bypass` (skip confirmations) |

Policy gates follow the pattern `UNIFI_POLICY_NETWORK_<CATEGORY>_<ACTION>` (most specific) down to `UNIFI_POLICY_<ACTION>` (global). Most specific wins.

Examples:
```bash
UNIFI_POLICY_NETWORK_NETWORKS_CREATE=true
UNIFI_POLICY_NETWORK_DEVICES_UPDATE=true
UNIFI_POLICY_NETWORK_ACL_RULES_DELETE=true
# Or server-wide:
UNIFI_POLICY_NETWORK_UPDATE=true
```

## Tool Categories

Valid values for `UNIFI_ENABLED_CATEGORIES` (eager mode):

| Category | Description |
|----------|-------------|
| `clients` | Client listing, blocking, guest auth |
| `devices` | Device listing, radio config, reboot, upgrade |
| `events` | Events and alarms |
| `acl` | MAC ACL rules (Layer 2 access control) |
| `firewall` | Firewall policies and IP groups |
| `hotspot` | Vouchers for guest network |
| `network` | Network/VLAN management |
| `port_forwards` | Port forwarding rules |
| `qos` | QoS/traffic shaping rules |
| `routing` | Static routes |
| `stats` | Statistics and metrics |
| `system` | System info, health, settings |
| `traffic_routes` | Policy-based routing |
| `usergroups` | Bandwidth profiles |
| `vpn` | VPN servers and clients |

## YAML Config Reference

The full config file lives at `src/unifi_network_mcp/config/config.yaml`. All values use OmegaConf interpolation so environment variables take precedence:

```yaml
unifi:
  host: ${UNIFI_HOST}
  username: ${UNIFI_USERNAME}
  password: ${UNIFI_PASSWORD}
  port: ${oc.env:UNIFI_PORT,443}
  site: ${oc.env:UNIFI_SITE,default}
  verify_ssl: ${oc.env:UNIFI_VERIFY_SSL,false}
  controller_type: ${oc.env:UNIFI_CONTROLLER_TYPE,auto}
  api_key: ${oc.env:UNIFI_API_KEY,""}

server:
  host: ${oc.env:UNIFI_MCP_HOST,0.0.0.0}
  port: ${oc.env:UNIFI_MCP_PORT,3000}
  log_level: INFO
  tool_registration_mode: ${oc.env:UNIFI_TOOL_REGISTRATION_MODE,lazy}

  http:
    enabled: ${oc.env:UNIFI_MCP_HTTP_ENABLED,false}
    transport: ${oc.env:UNIFI_MCP_HTTP_TRANSPORT,streamable-http}

permissions:
  # See permissions.md for the full defaults
  default:
    create: true
    update: true
    delete: false
```

You can override the config file location with `CONFIG_PATH=/path/to/config.yaml`.
