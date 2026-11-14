# Configuration — Site Manager Server

Configuration comes from the server's process environment. The server never loads a `.env` file from the working directory. To keep settings out of a client's config file, load a trusted env file in your launcher (for example Docker `env_file:`), or name a [per-user settings file](#per-user-settings-file).

## The API key

Create a key at [unifi.ui.com](https://unifi.ui.com) under Settings > API Keys, then give it to the server in exactly one of these ways:

| Variable | Use |
|---|---|
| `UNIFI_SITEMANAGER_API_KEY` | The key itself |
| `UNIFI_SITEMANAGER_API_KEY_FILE` | Path to a file holding the key |
| `UNIFI_SITEMANAGER_API_KEY_COMMAND` | A command that prints the key |

The key is read from these variables and nowhere else:

- Not from `UNIFI_API_KEY`, or any other shared `UNIFI_*` variable. That variable holds a console's local key, which must never be sent to the cloud.
- Not from `config.yaml` or a `CONFIG_PATH` file.

Without a key the server starts in setup mode: it answers the client, offers only `sitemanager_setup_status`, explains what to set, and makes no request.

The key covers every console the account can see. Treat it accordingly.

### How the key is resolved

- An empty `UNIFI_SITEMANAGER_API_KEY` counts as unset.
- Setting more than one of the three variables refuses startup and names the variables that conflict. Keep exactly one.
- A `_FILE` or `_COMMAND` value that cannot be read, resolves to an empty value, or holds more than one line refuses startup. Trailing newlines are dropped.
- `_FILE` takes a path. A leading `~` is expanded; otherwise give an absolute path. A file other users can read logs a warning; use `chmod 600`.
- `_COMMAND` is split like a shell command line but run without a shell. Give the helper's absolute path or a bare name found on `PATH`; a relative path is refused. The command must finish within 30 seconds.

```bash
# A file only you can read
export UNIFI_SITEMANAGER_API_KEY_FILE="$HOME/.config/unifi-mcp/sitemanager-api-key"

# A secret manager's CLI (1Password shown; any command that prints the key works)
export UNIFI_SITEMANAGER_API_KEY_COMMAND="op read op://Private/UniFi-Site-Manager/credential"
```

The shared [credential provider](../../../docs/credential-providers.md) contract covers platforms, process limits and executable lookup in detail. Where it describes a server-specific variable falling back to a shared one, that fallback does not apply to this key.

### Per-user settings file

`UNIFI_SETTINGS_FILE` names a file of `KEY=value` lines that the server applies to its environment at startup, before anything reads configuration. This is how a client without per-user server options, such as a Codex plugin, keeps the key provider out of its own config.

- The path must be absolute, such as `~/.config/unifi-mcp/sitemanager.env` (a leading `~` is expanded).
- The file must belong to the current user. A file other users can write is ignored; one they can read logs a warning. Use `chmod 600`.
- Only `UNIFI_` keys are accepted.
- A variable already set in the process environment wins over the same key in the file.
- Values are never logged.

## Destination

Requests go to `https://api.ui.com`. This is fixed and cannot be changed by configuration. The server does not follow redirects and ignores proxy environment variables.

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_SITEMANAGER_TIMEOUT_SECONDS` | `30` | Seconds to wait for one API response. A value that is not a positive number uses the default. |
| `UNIFI_SITEMANAGER_REDACT_SENSITIVE_FIELDS` | `true` | Redact secret-looking fields in responses (falls back to `UNIFI_REDACT_SENSITIVE_FIELDS`) |
| `UNIFI_SITEMANAGER_MCP_CONTENT_MODE` | `adaptive` | MCP response content mode (falls back to `UNIFI_MCP_CONTENT_MODE`) |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | `lazy`, `eager` or `meta_only` |
| `UNIFI_ENABLED_CATEGORIES` | all | Eager mode only: see [Tool categories](#tool-categories) |
| `UNIFI_ENABLED_TOOLS` | all | Eager mode only: specific tool names |
| `UNIFI_MCP_LOG_LEVEL` | `INFO` | Log level (logs go to stderr) |
| `UNIFI_SETTINGS_FILE` | none | [Per-user settings file](#per-user-settings-file), such as `~/.config/unifi-mcp/sitemanager.env` |

Settings are read once at startup. Restart the server, or start a new client session, after changing any of them.

There are no console settings (host, port, username, password, TLS verification or certificate pinning) and no event or websocket settings: this server has no console connection and no event stream.

## MCP response content

`UNIFI_SITEMANAGER_MCP_CONTENT_MODE` (falling back to `UNIFI_MCP_CONTENT_MODE`) controls how tool results are returned to the client.

| Mode | What the client gets |
|---|---|
| `adaptive` (default) | Decided per request from the MCP `protocolVersion` the client advertised during initialization, not from the client's name. `2025-06-18` or later: a short `content` text plus the full result once in `structuredContent`. Earlier, missing or malformed revisions: the full JSON in `content`. |
| `compat` | Always the full JSON in `content`. Use it for a client that reads results only from `content`, whatever revision it advertises. |
| `compact` | Always the short text plus the full result in `structuredContent`. |

The meta-tools (`sitemanager_tool_index`, `sitemanager_execute`, `sitemanager_batch`, `sitemanager_batch_status` and `sitemanager_load_tools`) return their result in `content` in every mode. For a tool run through `sitemanager_execute` or `sitemanager_batch_status`, `content` holds one JSON payload.

## HTTP transport

Stdio is the default. To serve HTTP:

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_MCP_HTTP_ENABLED` | `false` | Serve HTTP as well as stdio |
| `UNIFI_MCP_HOST` | `127.0.0.1` | Bind address |
| `UNIFI_MCP_PORT` | `3003` | Port |
| `UNIFI_MCP_HTTP_TRANSPORT` | `streamable-http` | `streamable-http` or `sse` |
| `UNIFI_SITEMANAGER_MCP_HTTP_AUTH_TOKEN` | none | Bearer token every request must carry (falls back to `UNIFI_MCP_HTTP_AUTH_TOKEN`) |
| `UNIFI_MCP_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host headers the server accepts, comma-separated (for a reverse proxy) |
| `UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION` | `true` | Check the Host header against `UNIFI_MCP_ALLOWED_HOSTS` |
| `UNIFI_MCP_HTTP_FORCE` | `false` | Serve HTTP from a process that is not PID 1 (local development only) |

Anyone who can reach the HTTP endpoint can read the whole account's inventory. Keep it on loopback or set an auth token.

The auth token is resolved in this order: `UNIFI_SITEMANAGER_MCP_HTTP_AUTH_TOKEN`, then `UNIFI_MCP_HTTP_AUTH_TOKEN`, then `server.http.auth_token` in a `CONFIG_PATH` file. Both variables accept the `_FILE` and `_COMMAND` forms. A token variable that is set but empty refuses startup rather than turning authentication off, and so does a token shorter than 32 characters or one holding whitespace or non-printable characters.

HTTP binds only in the container's main process (PID 1). A server started any other way with `UNIFI_MCP_HTTP_ENABLED=true` logs that HTTP was skipped and serves stdio only, unless `UNIFI_MCP_HTTP_FORCE=true`. Never set either variable in a client's MCP entry.

In Docker, the `unifi-sitemanager-mcp` service in `docker/docker-compose.yml` is in the opt-in `sitemanager` profile. It listens on `0.0.0.0:3003` inside the container and is published only on `127.0.0.1:3003` on the host. Other containers on the Compose network can reach it, so set a token before relying on it.

## Diagnostics

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_MCP_DIAGNOSTICS` | `false` | Log one line per tool call: tool name, duration, success, and the exception class on failure |
| `UNIFI_MCP_DIAG_LOG_TOOL_ARGS` | `true` | Accepted for compatibility; arguments are never logged |
| `UNIFI_MCP_DIAG_LOG_TOOL_RESULT` | `true` | Accepted for compatibility; results are never logged |
| `UNIFI_MCP_DIAG_MAX_PAYLOAD` | `2000` | Maximum characters of one diagnostic line |

Diagnostic lines carry no arguments, results, ids or request headers. There is no support-bundle tool on this server; see [Troubleshooting](troubleshooting.md#reporting-a-problem) for what to include in a report.

## Tracing

The MCP SDK records a span for every MCP message and continues a W3C trace context passed in the request's `_meta`. Setting an OTLP endpoint exports these spans. The Docker image includes the exporter; a pip or uvx install needs the `otel` extra (`unifi-sitemanager-mcp[otel]`), and a source checkout can add it with `uv sync --extra otel --package unifi-sitemanager-mcp`.

| Variable | Default | Purpose |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP collector endpoint; spans are exported only when this or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | `http/protobuf`, or `grpc` once `opentelemetry-exporter-otlp-proto-grpc` is installed |
| `OTEL_SERVICE_NAME` | `unifi-sitemanager-mcp` | Service name on exported spans |
| `OTEL_SDK_DISABLED` | `false` | `true` turns export off |

A span records the MCP method, the tool name, the JSON-RPC request id and the timing, not tool arguments or results. A call through `sitemanager_execute` or `sitemanager_batch` carries the meta-tool's name, not the name of the tool it runs.

## Permissions

There are no write tools, so there is nothing to permit or gate. See [permissions.md](permissions.md).

## Tool categories

For `UNIFI_ENABLED_CATEGORIES` in eager mode, and the `category` filter of `sitemanager_tool_index`:

| Category | Tools |
|---|---|
| `hosts` | `sitemanager_list_hosts`, `sitemanager_get_host` |
| `sites` | `sitemanager_list_sites` |
| `devices` | `sitemanager_list_devices` |
| `isp_metrics` | `sitemanager_get_isp_metrics`, `sitemanager_query_isp_metrics` |
| `sdwan` | `sitemanager_list_sdwan_configs`, `sitemanager_get_sdwan_config`, `sitemanager_get_sdwan_config_status` |

```bash
UNIFI_TOOL_REGISTRATION_MODE=eager UNIFI_ENABLED_CATEGORIES=hosts,sites
```

## Registration modes

| Mode | What the client sees |
|---|---|
| `lazy` (default) | The meta-tools and all nine tools |
| `eager` | The meta-tools except `sitemanager_load_tools`, and all nine tools (or the enabled subset) |
| `meta_only` | The meta-tools only; reach tools through `sitemanager_execute` |

Lazy mode lists every tool directly because `sitemanager_execute` is not marked read-only, and a client that permits only read-only tools would otherwise reach nothing. Clients discover tools through the standard `tools/list`; `sitemanager_tool_index` is an extra, filterable view. See [MCP discovery and meta-tools](../../../docs/tool-index.md).

## YAML config

The bundled `config.yaml` holds runtime settings only: server, HTTP, diagnostics, response policy and the request timeout. Each value can be set by the environment variable named above. To replace the file, set `CONFIG_PATH` to the absolute path of a YAML file you control; a relative path or a missing file refuses startup. The server never looks for a config file in the working directory.

`CONFIG_PATH` and `config.yaml` are never a source for the Site Manager API key. A key placed in a YAML file is ignored.
