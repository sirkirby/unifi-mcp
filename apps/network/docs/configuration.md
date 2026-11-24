# Configuration

The UniFi Network MCP server merges settings from three sources (highest priority first):

1. **Process environment variables** supplied by the launcher
2. **YAML config file** (`src/unifi_network_mcp/config/config.yaml`)
3. **Hardcoded defaults**

## Essential Variables

The Network server supports server-specific environment variables with the `UNIFI_NETWORK_` prefix. These take priority over the shared `UNIFI_*` variables, which serve as a fallback. For single-controller setups, the shared variables are all you need.

| Server-specific variable | Shared fallback | Required | Default | Description |
|--------------------------|-----------------|----------|---------|-------------|
| `UNIFI_NETWORK_HOST` | `UNIFI_HOST` | Yes | -- | Controller IP or hostname |
| `UNIFI_NETWORK_USERNAME` | `UNIFI_USERNAME` † | For session tools | `""` | Local admin username; omit for API-key-only inventory |
| `UNIFI_NETWORK_PASSWORD` | `UNIFI_PASSWORD` † | For session tools | `""` | Admin password; omit for API-key-only inventory |
| `UNIFI_NETWORK_API_KEY` | `UNIFI_API_KEY` † | No | `""` | Inventory reads and explicit Integration API tools; legacy mutations/full details may still require username/password. Public fallback has limited fields and separate UUIDs; see the README authentication section. |
| `UNIFI_NETWORK_PORT` | `UNIFI_PORT` | No | `443` | Controller HTTPS port |
| `UNIFI_NETWORK_SITE` | `UNIFI_SITE` | No | `default` | UniFi site name |
| `UNIFI_NETWORK_VERIFY_SSL` | `UNIFI_VERIFY_SSL` | No | `false` | TLS certificate verification; see [Checking the controller's identity](../../../docs/tls-verification.md) |
| `UNIFI_NETWORK_SSL_FINGERPRINT` | `UNIFI_SSL_FINGERPRINT` | No | none | SHA-256 fingerprint pinning the controller certificate; overrides verify_ssl |
| `UNIFI_NETWORK_WEBSOCKET_ENABLED` | -- | No | `true` | Start the real-time event listener that feeds `unifi_recent_events` |
| `UNIFI_NETWORK_EVENT_BUFFER_SIZE` | -- | No | `100` | Positive maximum events held in the websocket ring buffer; invalid values prevent startup |
| `UNIFI_NETWORK_EVENT_BUFFER_TTL` | -- | No | `300` | Positive seconds before buffered events expire; invalid values prevent startup |

**Resolution order:** `UNIFI_NETWORK_*` > `UNIFI_*` > YAML config > hardcoded default.

† **Credentials follow the host.** The shared `UNIFI_USERNAME`, `UNIFI_PASSWORD` and `UNIFI_API_KEY` (and their `_FILE` / `_COMMAND` spellings) are used only when `UNIFI_NETWORK_HOST` is unset or names the same console as `UNIFI_HOST`: the same host as written apart from letter case, on the same port (`UNIFI_NETWORK_PORT`, else `UNIFI_PORT`, else 443). No scheme, slash or space is stripped, and an IP address and a hostname for the same console count as different, so write both hosts the same way. When `UNIFI_NETWORK_HOST` names another console, set `UNIFI_NETWORK_USERNAME` and `UNIFI_NETWORK_PASSWORD` (and `UNIFI_NETWORK_API_KEY` if you use one): the server ignores the shared ones, says so at startup with a line such as `UNIFI_PASSWORD is set but not used: the host comes from UNIFI_NETWORK_HOST, which differs from UNIFI_HOST; set UNIFI_NETWORK_PASSWORD (or its _FILE/_COMMAND form).`, and its first login fails until they are set. Newer server releases do this; older releases sent the shared credentials to the other host instead, so the same setting is right for both. The other rows always fall back. See [credential providers](../../../docs/credential-providers.md#credentials-follow-the-host).

### Keeping the password out of the client environment

`UNIFI_NETWORK_PASSWORD` and `UNIFI_NETWORK_API_KEY` (and their `UNIFI_*` fallbacks, where those apply) each accept two indirect spellings, so the secret only ever exists inside the server process:

| Variable | Value |
|----------|-------|
| `UNIFI_NETWORK_PASSWORD_FILE` | Path to a file whose contents are the password (Docker and systemd secrets convention). Trailing newlines dropped. |
| `UNIFI_NETWORK_PASSWORD_COMMAND` | An absolute argv whose stdout is the password, for example `/usr/bin/pass show unifi/admin`. Run without a shell, in a neutral working directory, with stdin closed and stderr discarded. |

`UNIFI_NETWORK_API_KEY_FILE` and `UNIFI_NETWORK_API_KEY_COMMAND` behave the same way. Set exactly one spelling per level; every failure refuses startup with exit code 6, naming the variable and logging nothing the file or helper produced.

The indirections are honoured only for variables present in the environment the server was started with. [docs/credential-providers.md](../../../docs/credential-providers.md) is the contract: the supported platforms, the executable-resolution rule, the timeout and the process lifecycle.

The server does not discover or load `.env` files, including in its working directory or beside the installed package. Supply settings through exported variables, the MCP client's `env` block, or Docker `environment:` / `env_file:`. Use absolute paths for credential files. The launcher and any configuration files it explicitly loads must be controlled by the operator.

If you previously relied on automatic `.env` loading, configure your launcher to load a trusted file explicitly. For example:

```bash
uv run --env-file /absolute/path/to/trusted.env --with unifi-network-mcp unifi-network-mcp
```

Only select files you trust; explicitly loading a project's malicious env file in the launcher puts those values in the trusted process environment. Docker Compose deployments that already use `env_file:` continue to work.

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
| `UNIFI_DEFER_CONTROLLER_INIT` | `false` | By default the server answers the MCP client at once and connects to the controller in the background; tool calls wait for that connection for up to 15 seconds. Set `true` to make no connection at startup and connect on the first tool call instead. The real-time event listener starts in the background after the connection succeeds. |
| `UNIFI_META_TOOLS_ENABLED` | `true` | Eager mode only. Set to `false` to omit indirect meta-tools, including `unifi_get_support_bundle`; `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS` is then required. |
| `UNIFI_ENABLED_CATEGORIES` | — | Comma-separated tool categories to load (eager mode only) |
| `UNIFI_ENABLED_TOOLS` | — | Comma-separated tool names to register (eager mode only) |
| `CONFIG_PATH` | — | Path to a custom config YAML file |
| `UNIFI_SETTINGS_FILE` | — | Absolute path to a per-user file of `UNIFI_*` settings, read at startup; the process environment wins ([details](../../../README.md#configuration)) |

## MCP Response Content

`UNIFI_NETWORK_MCP_CONTENT_MODE` overrides the global `UNIFI_MCP_CONTENT_MODE`; if neither is set, the YAML value and then the `adaptive` default apply.

The `adaptive` and `compact` modes affect response compaction only for tool results that already provide structured output. The lazy-loading meta-tools (`*_tool_index`, `*_execute`, `*_batch`, `*_batch_status`, `*_batch_cancel`, and lazy-only `*_load_tools`) remain content-only and are independent of protocol-version response compatibility. For structured inner results, `*_execute` and `*_batch_status` expose one normalized JSON payload in `content` rather than a nested transport pair; content-only execute results remain unchanged. Response modes do not convert these meta-tools to `structuredContent`.

| Mode | Behavior |
|------|----------|
| `adaptive` (default) | Classifies the request by the canonical date-based `protocolVersion` advertised during MCP initialization, not by client product or application version. For structured tool results, MCP `2025-06-18` or later receives concise `content` plus the full result once in `structuredContent`; earlier, missing, or malformed revisions retain full compatibility JSON in `content`. |
| `compat` | Forces full compatibility JSON in `content` as well as the structured result. Use this for clients that consume the full result only from `content`, regardless of advertised revision. |
| `compact` | For structured tool results, forces concise `content` plus the full `structuredContent` result even when no capable protocol revision was negotiated. |

Network also bounds high-volume source data before MCP serialization: `unifi_get_dashboard` defaults to `summary=true`, and `unifi_list_rogue_aps` defaults to a summarized page of at most 100 records. Pass `summary=false` for full data within the selected dashboard request or rogue-AP page.

## Tool Registration Modes

Standard MCP clients discover currently registered tools with `tools/list`.
The meta-tools support lazy loading through filtered discovery, indirect
execution, batch orchestration, and optional direct registration. See [MCP Discovery and Lazy-Loading Meta-Tools](../../../docs/tool-index.md).

| Mode | Initial `tools/list` behavior | Best fit |
|------|-------------------------------|----------|
| `lazy` (default) | Meta-tools plus `unifi_load_tools`, and the read-only `unifi_get_incident_evidence` and `unifi_get_client_details`; other domain tools load on demand | Production LLM clients with limited context |
| `eager` | Meta-tools plus all selected Network tools registered directly | Standard MCP clients and dev consoles |
| `meta_only` | Core meta-tools only; use `unifi_execute` for operations | Maximum context control |

## HTTP Transport

HTTP is disabled by default. The stdio transport is recommended for most use cases.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_HTTP_ENABLED` | `false` | Enable HTTP transport |
| `UNIFI_MCP_HTTP_TRANSPORT` | `streamable-http` | `streamable-http` (recommended) or `sse` (legacy) |
| `UNIFI_MCP_HOST` | `127.0.0.1` | HTTP bind address; remote access requires an authenticated proxy or relay |
| `UNIFI_MCP_PORT` | `3000` | HTTP bind port |
| `UNIFI_MCP_HTTP_FORCE` | `false` | Force HTTP in non-container environments |
| `UNIFI_MCP_STDIO_ENABLED` | `true` | Set `false` to serve HTTP alone from a process that is not PID 1 (an init-managed container or a service manager); needs `UNIFI_MCP_HTTP_ENABLED=true` and `UNIFI_MCP_HTTP_FORCE=true` |
| `UNIFI_MCP_HTTP_AUTH_TOKEN` | unset | Require `Authorization: Bearer <token>` on every HTTP request; at least 32 printable ASCII characters. `UNIFI_NETWORK_MCP_HTTP_AUTH_TOKEN` overrides it for this server, and both accept the `_FILE` and `_COMMAND` spellings. See [HTTP bearer token](transports.md#http-bearer-token) |
| `UNIFI_MCP_HTTP_AUTH_TRUSTED_NETWORKS` | unset | IP addresses or CIDR networks whose requests skip the bearer token: the pinned address of an authenticating proxy in front of the server, never a whole container network. Docker Compose passes it from `.env`. See [Trusted networks](transports.md#trusted-networks) |

## Security

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Allowed hostnames (for reverse proxy setups) |
| `UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION` | `true` | DNS rebinding protection |

## Diagnostics

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_MCP_DIAGNOSTICS` | `false` | Enable structured logging for tool calls and API requests |
| `UNIFI_MCP_DIAG_LOG_TOOL_ARGS` | `true` | Deprecated compatibility setting; arguments are never logged |
| `UNIFI_MCP_DIAG_LOG_TOOL_RESULT` | `true` | Deprecated compatibility setting; result payloads are never logged |
| `UNIFI_MCP_DIAG_MAX_PAYLOAD` | `2000` | Max characters for diagnostic payloads |

Diagnostics include the tool name or HTTP method, duration, boolean outcome when available, and exception class. They omit arguments, results, controller request/response bodies, paths, and exception messages, even when the legacy payload flags are enabled.

## Tracing

The MCP SDK records a span for every MCP message (`tools/call <tool>` carries `gen_ai.tool.name`) and continues a W3C trace context passed in the request's `_meta`, so a gateway or client that sends one sees the server's spans in its own trace. Setting an OTLP endpoint exports these spans. The Docker image includes the exporter; pip and uvx installs need the `otel` extra (`unifi-network-mcp[otel]`).

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP collector endpoint; spans are exported only when this or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | `http/protobuf`, or `grpc` once `opentelemetry-exporter-otlp-proto-grpc` is installed |
| `OTEL_SERVICE_NAME` | `unifi-network-mcp` | Service name on exported spans |

The other standard `OTEL_*` variables apply as usual, for example `OTEL_TRACES_SAMPLER`, `OTEL_RESOURCE_ATTRIBUTES` and `OTEL_EXPORTER_OTLP_HEADERS`. A span records the MCP method, the tool name, the JSON-RPC request ID and the timing, not tool arguments or results. A call through `unifi_execute` or `unifi_batch`, which the `lazy` and `meta_only` registration modes rely on, carries the meta tool's name, not the name of the tool it runs.

A failed request records its error message in the span status. For `resources/read`, the SDK's message contains the requested resource URI. Tools return their errors as results; if an exception escapes a request handler anyway, the SDK also records its type, message and stack trace on the span.

## Controller Operation Gate

Every tool call takes its turn at this server's operation gate for the controller before it reaches the controller. Confirmed writes (create, update and delete tools called with `confirm=true`) run one at a time, in the order they arrive, whether they come from direct tool calls, `unifi_execute` or `unifi_batch`. Reads and previews run side by side, up to a cap, and never wait behind writes. The guarantee is per server process: two servers, or two copies of one, pointed at the same controller do not coordinate.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_NETWORK_WRITE_HOLD_SECONDS` / `UNIFI_WRITE_HOLD_SECONDS` | `120` | How long one write may hold its turn (10 to 3600). Once it has held longer, calls queued behind it are refused as busy, with nothing sent; a write's own controller requests stop at this budget. |
| `UNIFI_NETWORK_CALL_WAIT_SECONDS` / `UNIFI_CALL_WAIT_SECONDS` | `25` | How long a direct tool call waits for its turn before it is refused as busy (1 to 3600). Batch jobs wait as long as the queue keeps moving. |
| `UNIFI_NETWORK_READ_CONCURRENCY` / `UNIFI_READ_CONCURRENCY` | `8` | Reads that may run at once (1 to 64). |

A value that is not a number in range stops the server at startup, naming the variable. Unlike the preview-token lifetime, which is clamped, these are not guessed at: a wrong lock budget is a configuration error to fix. A call refused as busy returns `success: false` with the reason, plus `mutation_applied: false` for a confirmed write. `unifi_batch_cancel` withdraws batch jobs that are still queued. The support bundle reports the gate's state as flags and bucketed counts. This server has one gate, for its own controller, so a call never waits for one gate while holding another.

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
  host: ${oc.env:UNIFI_NETWORK_HOST,""}
  username: ${oc.env:UNIFI_NETWORK_USERNAME,""}
  password: ${oc.env:UNIFI_NETWORK_PASSWORD,""}
  port: ${oc.env:UNIFI_NETWORK_PORT,443}
  site: ${oc.env:UNIFI_NETWORK_SITE,default}
  verify_ssl: ${oc.env:UNIFI_NETWORK_VERIFY_SSL,false}
  controller_type: ${oc.env:UNIFI_NETWORK_CONTROLLER_TYPE,auto}
  api_key: ${oc.env:UNIFI_NETWORK_API_KEY,""}

server:
  host: ${oc.env:UNIFI_MCP_HOST,127.0.0.1}
  port: ${oc.env:UNIFI_MCP_PORT,3000}
  log_level: INFO
  tool_registration_mode: ${oc.env:UNIFI_TOOL_REGISTRATION_MODE,lazy}
  defer_controller_init: ${oc.env:UNIFI_DEFER_CONTROLLER_INIT,false}
  meta_tools_enabled: ${oc.env:UNIFI_META_TOOLS_ENABLED,true}

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

You can override the config file location with `CONFIG_PATH=/absolute/path/to/config.yaml` in the process environment. Relative paths are rejected. The server never automatically loads `config/config.yaml` from the working directory; existing custom YAML deployments must select their trusted file explicitly.
