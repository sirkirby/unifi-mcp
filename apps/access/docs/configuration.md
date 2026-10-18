# Configuration

The UniFi Access MCP server merges settings from three sources (highest priority first):

1. **Process environment variables** supplied by the launcher
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

### Keeping the password out of the client environment

`UNIFI_ACCESS_PASSWORD` and `UNIFI_ACCESS_API_KEY` (and their `UNIFI_*` fallbacks) each accept two indirect spellings, so the secret only ever exists inside the server process:

| Variable | Value |
|----------|-------|
| `UNIFI_ACCESS_PASSWORD_FILE` | Path to a file whose contents are the password (Docker and systemd secrets convention). Trailing newlines dropped. |
| `UNIFI_ACCESS_PASSWORD_COMMAND` | An absolute argv whose stdout is the password, for example `/usr/bin/pass show unifi/admin`. Run without a shell, in a neutral working directory, with stdin closed and stderr discarded. |

`UNIFI_ACCESS_API_KEY_FILE` and `UNIFI_ACCESS_API_KEY_COMMAND` behave the same way. Set exactly one spelling per level; every failure refuses startup with exit code 6, naming the variable and logging nothing the file or helper produced.

The indirections are honoured only for variables present in the environment the server was started with. [docs/credential-providers.md](../../../docs/credential-providers.md) is the contract: the supported platforms, the executable-resolution rule, the timeout and the process lifecycle.

The server does not discover or load `.env` files, including in its working directory or beside the installed package. Supply settings through exported variables, the MCP client's `env` block, or Docker `environment:` / `env_file:`. Use absolute paths for credential files. The launcher and any configuration files it explicitly loads must be controlled by the operator.

If you previously relied on automatic `.env` loading, configure your launcher to load a trusted file explicitly. For example:

```bash
uv run --env-file /absolute/path/to/trusted.env --with unifi-access-mcp unifi-access-mcp
```

Only select files you trust; explicitly loading a project's malicious env file in the launcher puts those values in the trusted process environment. Docker Compose deployments that already use `env_file:` continue to work.

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

When both paths are available, each tool selects the appropriate one. Visitor list/get/create/delete operations require the Access Developer API token on port 12445; credential management, policies, and other proxy-backed capabilities require the local session. See the `auth` metadata on each tool for its exact requirement.

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

`UNIFI_ACCESS_MCP_CONTENT_MODE` overrides the global `UNIFI_MCP_CONTENT_MODE`; if neither is set, the YAML value and then the `adaptive` default apply.

The `adaptive` and `compact` modes affect response compaction only for tool results that already provide structured output. The lazy-loading meta-tools (`*_tool_index`, `*_execute`, `*_batch`, `*_batch_status`, and lazy-only `*_load_tools`) remain content-only and are independent of protocol-version response compatibility. For structured inner results, `*_execute` and `*_batch_status` expose one normalized JSON payload in `content` rather than a nested transport pair; content-only execute results remain unchanged. Response modes do not convert these meta-tools to `structuredContent`.

| Mode | Behavior |
|------|----------|
| `adaptive` (default) | Classifies the request by the canonical date-based `protocolVersion` advertised during MCP initialization, not by client product or application version. For structured tool results, MCP `2025-06-18` or later receives concise `content` plus the full result once in `structuredContent`; earlier, missing, or malformed revisions retain full compatibility JSON in `content`. |
| `compat` | Forces full compatibility JSON in `content` as well as the structured result. Use this for clients that consume the full result only from `content`, regardless of advertised revision. |
| `compact` | For structured tool results, forces concise `content` plus the full `structuredContent` result even when no capable protocol revision was negotiated. |

When Network runs alongside Access, its high-volume source defaults remain independently bounded: `unifi_get_dashboard` uses `summary=true`, and `unifi_list_rogue_aps` returns a summarized page of at most 100 records; `summary=false` restores full data within the selected response.

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
| `UNIFI_MCP_HOST` | `127.0.0.1` | HTTP bind address; remote access requires an authenticated proxy or relay |
| `UNIFI_MCP_PORT` | `3002` | HTTP bind port |
| `UNIFI_MCP_HTTP_FORCE` | `false` | Force HTTP in non-container environments |

**Note:** The Access server defaults to port 3002 (vs. 3000 for Network, 3001 for Protect) to allow running all servers simultaneously.

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
The meta-tools support lazy loading through filtered discovery, indirect
execution, batch orchestration, and optional direct registration. See [MCP Discovery and Lazy-Loading Meta-Tools](../../../docs/tool-index.md).

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
  host: ${oc.env:UNIFI_MCP_HOST,127.0.0.1}
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

You can override the config file location with `CONFIG_PATH=/absolute/path/to/config.yaml` in the process environment. Relative paths are rejected. The server never automatically loads `config/config.yaml` from the working directory; existing custom YAML deployments must select their trusted file explicitly.
