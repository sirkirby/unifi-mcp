# Configuration

The UniFi Protect MCP server merges settings from three sources (highest priority first):

1. **Process environment variables** supplied by the launcher
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
| `UNIFI_PROTECT_API_KEY` | `UNIFI_API_KEY` | For public settings | `""` | Required for camera HDR/microphone volume, light power/brightness/PIR sensitivity/duration, sensor settings, viewer liveview assignments, and per-camera chime ring settings; username/password still required |

**Resolution order:** `UNIFI_PROTECT_*` > `UNIFI_*` > YAML config > hardcoded default.

### Keeping the password out of the client environment

`UNIFI_PROTECT_PASSWORD` and `UNIFI_PROTECT_API_KEY` (and their `UNIFI_*` fallbacks) each accept two indirect spellings, so the secret only ever exists inside the server process:

| Variable | Value |
|----------|-------|
| `UNIFI_PROTECT_PASSWORD_FILE` | Path to a file whose contents are the password (Docker and systemd secrets convention). Trailing newlines dropped. |
| `UNIFI_PROTECT_PASSWORD_COMMAND` | An absolute argv whose stdout is the password, for example `/usr/bin/pass show unifi/admin`. Run without a shell, in a neutral working directory, with stdin closed and stderr discarded. |

`UNIFI_PROTECT_API_KEY_FILE` and `UNIFI_PROTECT_API_KEY_COMMAND` behave the same way. Set exactly one spelling per level; every failure refuses startup with exit code 6, naming the variable and logging nothing the file or helper produced.

The indirections are honoured only for variables present in the environment the server was started with. [docs/credential-providers.md](../../../docs/credential-providers.md) is the contract: the supported platforms, the executable-resolution rule, the timeout and the process lifecycle.

The server does not discover or load `.env` files, including in its working directory or beside the installed package. Supply settings through exported variables, the MCP client's `env` block, or Docker `environment:` / `env_file:`. Use absolute paths for credential files. The launcher and any configuration files it explicitly loads must be controlled by the operator.

If you previously relied on automatic `.env` loading, configure your launcher to load a trusted file explicitly. For example:

```bash
uv run --env-file /absolute/path/to/trusted.env --with unifi-protect-mcp unifi-protect-mcp
```

Only select files you trust; explicitly loading a project's malicious env file in the launcher puts those values in the trusted process environment. Docker Compose deployments that already use `env_file:` continue to work.

## Server Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_LOG_LEVEL` | `INFO` | Logging level |
| `UNIFI_AUTO_CONFIRM` | `false` | Skip preview-then-confirm for mutations (for automation) |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | Tool loading: `lazy`, `eager`, or `meta_only` |
| `UNIFI_ENABLED_CATEGORIES` | -- | Comma-separated tool categories to load (eager mode only) |
| `UNIFI_ENABLED_TOOLS` | -- | Comma-separated tool names to register (eager mode only) |
| `CONFIG_PATH` | -- | Path to a custom config YAML file |
| `UNIFI_SETTINGS_FILE` | -- | Absolute path to a per-user file of `UNIFI_*` settings, read at startup; the process environment wins ([details](../../../README.md#configuration)) |

## MCP Response Content

`UNIFI_PROTECT_MCP_CONTENT_MODE` overrides the global `UNIFI_MCP_CONTENT_MODE`; if neither is set, the YAML value and then the `adaptive` default apply.

The `adaptive` and `compact` modes affect response compaction only for tool results that already provide structured output. The lazy-loading meta-tools (`*_tool_index`, `*_execute`, `*_batch`, `*_batch_status`, and lazy-only `*_load_tools`) remain content-only and are independent of protocol-version response compatibility. For structured inner results, `*_execute` and `*_batch_status` expose one normalized JSON payload in `content` rather than a nested transport pair; content-only execute results remain unchanged. Response modes do not convert these meta-tools to `structuredContent`.

| Mode | Behavior |
|------|----------|
| `adaptive` (default) | Classifies the request by the canonical date-based `protocolVersion` advertised during MCP initialization, not by client product or application version. For structured tool results, MCP `2025-06-18` or later receives concise `content` plus the full result once in `structuredContent`; earlier, missing, or malformed revisions retain full compatibility JSON in `content`. |
| `compat` | Forces full compatibility JSON in `content` as well as the structured result. Use this for clients that consume the full result only from `content`, regardless of advertised revision. |
| `compact` | For structured tool results, forces concise `content` plus the full `structuredContent` result even when no capable protocol revision was negotiated. |

When Network runs alongside Protect, its high-volume source defaults remain independently bounded: `unifi_get_dashboard` uses `summary=true`, and `unifi_list_rogue_aps` returns a summarized page of at most 100 records; `summary=false` restores full data within the selected response.

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
| `UNIFI_MCP_HOST` | `127.0.0.1` | HTTP bind address; remote access requires an authenticated proxy or relay |
| `UNIFI_MCP_PORT` | `3001` | HTTP bind port |
| `UNIFI_MCP_HTTP_FORCE` | `false` | Force HTTP in non-container environments |

**Note:** The Protect server defaults to port 3001 (vs. 3000 for the Network server) to allow running both servers simultaneously.

## Diagnostics

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_DIAGNOSTICS` | `false` | Enable structured logging for tool calls and API requests |
| `UNIFI_MCP_DIAG_LOG_TOOL_ARGS` | `true` | Deprecated compatibility setting; arguments are never logged |
| `UNIFI_MCP_DIAG_LOG_TOOL_RESULT` | `true` | Deprecated compatibility setting; result payloads are never logged |
| `UNIFI_MCP_DIAG_MAX_PAYLOAD` | `2000` | Max characters for diagnostic payloads |

Diagnostics log operation metadata only. Controller payloads, paths, and exception messages are omitted regardless of the legacy payload flags.

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
The meta-tools support lazy loading through filtered discovery, indirect
execution, batch orchestration, and optional direct registration. See [MCP Discovery and Lazy-Loading Meta-Tools](../../../docs/tool-index.md).

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
  host: ${oc.env:UNIFI_MCP_HOST,127.0.0.1}
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

You can override the config file location with `CONFIG_PATH=/absolute/path/to/config.yaml` in the process environment. Relative paths are rejected. The server never automatically loads `config/config.yaml` from the working directory; existing custom YAML deployments must select their trusted file explicitly.
