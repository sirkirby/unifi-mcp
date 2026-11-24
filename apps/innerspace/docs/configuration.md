# Configuration — InnerSpace Server

Configuration comes from the server's process environment. The server never loads a `.env` file from the working directory. To keep settings out of a client's config file, load a trusted env file in your launcher (for example Docker `env_file:`), or name a per-user settings file with an absolute `UNIFI_SETTINGS_FILE` path.

## The console login

InnerSpace is read and written through a console login session. There is no API key setting: a console's local `UNIFI_API_KEY` is never read for this server and never sent to InnerSpace.

| Variable | Use |
|---|---|
| `UNIFI_INNERSPACE_HOST` | Console address (falls back to `UNIFI_HOST`) |
| `UNIFI_INNERSPACE_USERNAME` | Account name (falls back to `UNIFI_USERNAME` †) |
| `UNIFI_INNERSPACE_PASSWORD` | Account password (falls back to `UNIFI_PASSWORD` †) |
| `UNIFI_INNERSPACE_PORT` | Console HTTPS port, default `443` (falls back to `UNIFI_PORT`) |

† **Credentials follow the host.** The shared `UNIFI_USERNAME` and `UNIFI_PASSWORD` (and the password's `_FILE` / `_COMMAND` spellings) are used only when `UNIFI_INNERSPACE_HOST` is unset or names the same console as `UNIFI_HOST`: the same host as written apart from letter case, on the same port (`UNIFI_INNERSPACE_PORT`, else `UNIFI_PORT`, else 443). No scheme, slash or space is stripped, and an IP address and a hostname for the same console count as different, so write both hosts the same way. When `UNIFI_INNERSPACE_HOST` names another console, or `UNIFI_HOST` is not set, set `UNIFI_INNERSPACE_USERNAME` and `UNIFI_INNERSPACE_PASSWORD`. The server ignores the shared ones and names each one it ignored, without its value, in a startup warning and in the login error a tool call returns, for example `UNIFI_PASSWORD is set but not used: the host comes from UNIFI_INNERSPACE_HOST, which differs from UNIFI_HOST; set UNIFI_INNERSPACE_PASSWORD (or its _FILE/_COMMAND form).` The host and port always fall back. See [credential providers](../../../docs/credential-providers.md#credentials-follow-the-host).

The password also takes a `_FILE` form (a path to a file holding the value) and a `_COMMAND` form (a command that prints it), under the shared [credential provider](../../../docs/credential-providers.md) rules; prefer one of them. The username takes neither: set it directly.

The account must be able to open the InnerSpace application on the console, for example a Super Admin. A console that refuses the session for InnerSpace answers with the access error described in [troubleshooting](troubleshooting.md#the-console-refused-the-session-for-innerspace).

Without a host the server starts in setup mode: it answers the client, offers only `innerspace_setup_status`, explains what to set, and makes no request. With a host that cannot be reached at startup the server still serves; each call returns fixed text until the console answers, and the first call after it does logs in once.

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_INNERSPACE_VERIFY_SSL` | `false` | Verify the console certificate against the system's trusted CAs |
| `UNIFI_INNERSPACE_SSL_FINGERPRINT` | none | Pin the console certificate by SHA-256 fingerprint (falls back to `UNIFI_SSL_FINGERPRINT`) |
| `UNIFI_INNERSPACE_REDACT_SENSITIVE_FIELDS` | `true` | Redact secret-looking fields in responses (falls back to `UNIFI_REDACT_SENSITIVE_FIELDS`) |
| `UNIFI_INNERSPACE_MCP_CONTENT_MODE` | `adaptive` | MCP response content mode (falls back to `UNIFI_MCP_CONTENT_MODE`) |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | `lazy`, `eager` or `meta_only` |
| `UNIFI_ENABLED_CATEGORIES` | all | Eager mode only: see [Tool categories](#tool-categories) |
| `UNIFI_INNERSPACE_READ_ONLY` | `false` | Refuse every write, previews included (falls back to `UNIFI_READ_ONLY`) |
| `UNIFI_INNERSPACE_TOOL_PERMISSION_MODE` | `confirm` | `bypass` applies writes without a preview (falls back to `UNIFI_TOOL_PERMISSION_MODE`) |
| `UNIFI_INNERSPACE_REQUIRE_PREVIEW_TOKEN` | `false` | `true` makes `confirm=true` carry the token of a preview of the same arguments (falls back to `UNIFI_REQUIRE_PREVIEW_TOKEN`) |
| `UNIFI_POLICY_INNERSPACE_<CATEGORY>_<ACTION>` | allowed | `false` turns off one kind of write; see [permissions](permissions.md) |
| `UNIFI_ENABLED_TOOLS` | all | Eager mode only: specific tool names |
| `UNIFI_MCP_LOG_LEVEL` | `INFO` | Log level (logs go to stderr) |
| `UNIFI_SETTINGS_FILE` | none | Per-user settings file of `KEY=value` lines, applied before configuration is read |

Settings are read once at startup. Restart the server, or start a new client session, after changing any of them. There are no event or websocket settings: this server has no event stream. A `UNIFI_POLICY_INNERSPACE_*` name that matches no gate is reported in the log at startup.

## Console operation gate

Every tool call takes its turn at this server's operation gate for the console before it reaches the console. Confirmed writes (the write tools called with `confirm=true`) run one at a time, in the order they arrive, whether they come from direct tool calls, `innerspace_execute` or `innerspace_batch`. Reads, previews and plan image resource reads run side by side, up to a cap, and never wait behind writes. The guarantee is per server process: two servers, or two copies of one, pointed at the same console do not coordinate.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_INNERSPACE_WRITE_HOLD_SECONDS` / `UNIFI_WRITE_HOLD_SECONDS` | `120` | How long one write may hold its turn (10 to 3600). Once it has held longer, calls queued behind it are refused as busy, with nothing sent. |
| `UNIFI_INNERSPACE_CALL_WAIT_SECONDS` / `UNIFI_CALL_WAIT_SECONDS` | `25` | How long a direct tool call waits for its turn before it is refused as busy (1 to 3600). Batch jobs wait as long as the queue keeps moving. |
| `UNIFI_INNERSPACE_READ_CONCURRENCY` / `UNIFI_READ_CONCURRENCY` | `8` | Reads that may run at once (1 to 64). |

A value that is not a number in range stops the server at startup, naming the variable. A call refused as busy returns `success: false` with the reason, plus `mutation_applied: false` for a confirmed write, and nothing is sent to the console. `innerspace_batch_cancel` withdraws batch jobs that are still queued.

## TLS

Consoles usually present a self-signed certificate, so verification is off by default. Choose one of:

- Pin the certificate: set `UNIFI_INNERSPACE_SSL_FINGERPRINT` (or `UNIFI_SSL_FINGERPRINT`) to the console certificate's SHA-256 fingerprint. A pin overrides `UNIFI_INNERSPACE_VERIFY_SSL`. A malformed pin stops the server at startup with exit code 2 and a log line that does not repeat the value.
- Verify against trusted CAs: set `UNIFI_INNERSPACE_VERIFY_SSL=true`.

With neither, the server logs one warning at its first connection that the console certificate is not checked. See [TLS verification](../../../docs/tls-verification.md) for how to read a fingerprint.

The session client never follows redirects and ignores proxy environment variables, so the session cookie cannot be sent anywhere but the console you named.

## MCP response content

`UNIFI_INNERSPACE_MCP_CONTENT_MODE` (falling back to `UNIFI_MCP_CONTENT_MODE`) controls how tool results are returned to the client.

| Mode | What the client gets |
|---|---|
| `adaptive` (default) | Decided per request from the MCP `protocolVersion` the client advertised during initialization, not from the client's name. `2025-06-18` or later: a short `content` text plus the full result once in `structuredContent`. Earlier, missing or malformed revisions: the full JSON in `content`. |
| `compat` | Always the full JSON in `content`. |
| `compact` | Always the short text plus the full result in `structuredContent`. |

The meta-tools (`innerspace_tool_index`, `innerspace_execute`, `innerspace_batch`, `innerspace_batch_status`, `innerspace_batch_cancel` and `innerspace_load_tools`) return their result in `content` in every mode.

## HTTP transport

Stdio is the default. To serve HTTP:

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_MCP_HTTP_ENABLED` | `false` | Serve HTTP as well as stdio |
| `UNIFI_MCP_HOST` | `127.0.0.1` | Bind address |
| `UNIFI_MCP_PORT` | `3005` | Port |
| `UNIFI_MCP_HTTP_TRANSPORT` | `streamable-http` | `streamable-http` or `sse` |
| `UNIFI_INNERSPACE_MCP_HTTP_AUTH_TOKEN` | none | Bearer token every request must carry (falls back to `UNIFI_MCP_HTTP_AUTH_TOKEN`) |
| `UNIFI_INNERSPACE_MCP_HTTP_AUTH_TRUSTED_NETWORKS` | none | IP addresses or CIDR networks whose requests skip the bearer token: the pinned address of an authenticating proxy, never a whole container network. Falls back to `UNIFI_MCP_HTTP_AUTH_TRUSTED_NETWORKS`; empty turns the exemption off. Docker Compose passes only this server-level spelling. See [Trusted networks](../../network/docs/transports.md#trusted-networks) |
| `UNIFI_MCP_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host headers the server accepts, comma-separated (for a reverse proxy) |
| `UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION` | `true` | Check the Host header against `UNIFI_MCP_ALLOWED_HOSTS` |
| `UNIFI_MCP_HTTP_FORCE` | `false` | Serve HTTP from a process that is not PID 1 (local development only) |
| `UNIFI_MCP_STDIO_ENABLED` | `true` | Set `false` to serve HTTP alone from a process that is not PID 1 (an init-managed container or a service manager); needs `UNIFI_MCP_HTTP_ENABLED=true` and `UNIFI_MCP_HTTP_FORCE=true` |

Anyone who can reach the HTTP endpoint can read the project's floor plans, walls and device positions. Keep it on loopback or set an auth token. The token is resolved in this order: `UNIFI_INNERSPACE_MCP_HTTP_AUTH_TOKEN`, then `UNIFI_MCP_HTTP_AUTH_TOKEN`, then `server.http.auth_token` in a `CONFIG_PATH` file; both variables accept the `_FILE` and `_COMMAND` forms. A token that is set but empty, shorter than 32 characters, or holding whitespace refuses startup rather than turning authentication off.

HTTP binds only in the container's main process (PID 1). Started any other way with `UNIFI_MCP_HTTP_ENABLED=true`, the server logs that HTTP was skipped and serves stdio only, unless `UNIFI_MCP_HTTP_FORCE=true`. Outside PID 1, stdio stays the primary transport; `UNIFI_MCP_STDIO_ENABLED=false` serves HTTP alone. Never set these variables in a client's MCP entry.

### Docker Compose

The `unifi-innerspace-mcp` service in `docker/docker-compose.yml` is in the opt-in `innerspace` profile, so it does not start with the default stack. The Compose service builds the image from this checkout; the published image is `ghcr.io/sirkirby/unifi-innerspace-mcp`.

```bash
export UNIFI_INNERSPACE_HOST=192.168.1.1
export UNIFI_INNERSPACE_USERNAME=innerspace-agent
export UNIFI_INNERSPACE_PASSWORD="$(cat "$HOME/.config/unifi-mcp/innerspace-password")"
export UNIFI_INNERSPACE_MCP_HTTP_AUTH_TOKEN="$(cat "$HOME/.config/unifi-mcp/innerspace-http-token")"
docker compose -f docker/docker-compose.yml --profile innerspace up --build unifi-innerspace-mcp
```

The example passes the password itself because the service mounts no files: a `_FILE` path is read inside the container, so `UNIFI_INNERSPACE_PASSWORD_FILE` works only with a read-only mount you add in an override file, for example `docker/docker-compose.override.yml`:

```yaml
services:
  unifi-innerspace-mcp:
    volumes:
      - ${HOME}/.config/unifi-mcp/innerspace-password:/run/secrets/innerspace-password:ro
```

Then set `UNIFI_INNERSPACE_PASSWORD_FILE=/run/secrets/innerspace-password` instead of the password.

The service listens on `0.0.0.0:3005` inside the container and is published only on `127.0.0.1:3005` on the host. Other containers on the Compose network can reach it, so set the bearer token before relying on it: the service passes the token variables through only when they are set in your shell, and it does not generate one. It receives only its own `UNIFI_INNERSPACE_*` variables (and the HTTP token variables), never the shared `.env` file the other services load, and it is not in the relay's default server list. Compose takes those values from your shell, from `docker/.env`, or from a file named with `--env-file`. An unset port or `UNIFI_INNERSPACE_VERIFY_SSL` takes the server's default.

## Diagnostics

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_MCP_DIAGNOSTICS` | `false` | Log one line per tool call: tool name, duration, success, and the exception class on failure |
| `UNIFI_MCP_DIAG_LOG_TOOL_ARGS` | `true` | Accepted for compatibility; arguments are never logged |
| `UNIFI_MCP_DIAG_LOG_TOOL_RESULT` | `true` | Accepted for compatibility; results are never logged |
| `UNIFI_MCP_DIAG_MAX_PAYLOAD` | `2000` | Maximum characters of one diagnostic line |

Logs carry the operation, a route template and the exception class, never a response body, the console address, a request path or an exception's text. There is no support-bundle tool on this server; see [Troubleshooting](troubleshooting.md#reporting-a-problem).

## Tracing

The MCP SDK records a span for every MCP message. Setting an OTLP endpoint exports them. The Docker image includes the exporter; a pip or uvx install needs the `otel` extra (`unifi-innerspace-mcp[otel]`), and a source checkout can add it with `uv sync --extra otel --package unifi-innerspace-mcp`.

| Variable | Default | Purpose |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP collector endpoint; spans are exported only when this or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set |
| `OTEL_SERVICE_NAME` | `unifi-innerspace-mcp` | Service name on exported spans |
| `OTEL_SDK_DISABLED` | `false` | `true` turns export off |

A span records the MCP method, the tool name, the JSON-RPC request id and the timing, not tool arguments or results.

## Tool categories

For `UNIFI_ENABLED_CATEGORIES` in eager mode, and the `category` filter of `innerspace_tool_index`:

| Category | Tools |
|---|---|
| `status` | `innerspace_get_status` |
| `project` | `innerspace_get_project`, `innerspace_list_walls`, `innerspace_set_project_unit` |
| `floor_plans` | `innerspace_list_floor_plans`, `innerspace_get_plan_asset`, `innerspace_rename_floor_plan`, `innerspace_set_floor_attenuation`, `innerspace_reorder_floor_plans`, `innerspace_set_plan_scale` |
| `devices` | `innerspace_list_placed_devices`, `innerspace_list_access_points`, `innerspace_list_switches`, `innerspace_list_inventory` |
| `walls` | `innerspace_create_walls`, `innerspace_update_walls`, `innerspace_remove_walls` |
| `wall_types` | `innerspace_create_wall_type`, `innerspace_update_wall_type` |
| `attenuation` | `innerspace_create_attenuation_objects`, `innerspace_update_attenuation_objects`, `innerspace_remove_attenuation_objects`, `innerspace_create_attenuation_object_type`, `innerspace_update_attenuation_object_type` |

The same names, upper-cased, form the policy gates: `UNIFI_POLICY_INNERSPACE_WALL_TYPES_UPDATE=false`.

```bash
UNIFI_TOOL_REGISTRATION_MODE=eager UNIFI_ENABLED_CATEGORIES=status,floor_plans
```

## Registration modes

| Mode | What the client sees |
|---|---|
| `lazy` (default) | The meta-tools and the nine read tools; reach the writes through `innerspace_execute` or `innerspace_load_tools` |
| `eager` | The meta-tools except `innerspace_load_tools`, and all 24 tools (or the enabled subset) |
| `meta_only` | The meta-tools only; reach tools through `innerspace_execute` |

Lazy mode lists the read tools directly because `innerspace_execute` is not marked read-only, and a client that permits only read-only tools would otherwise reach nothing. The writes stay behind the dispatcher, where a client asks before running them. See [MCP discovery and meta-tools](../../../docs/tool-index.md).

## YAML config

The bundled `config.yaml` holds the console connection settings, server, HTTP, diagnostics and response policy. Each value can be set by the environment variable named above. To replace the file, set `CONFIG_PATH` to the absolute path of a YAML file you control; a relative path or a missing file refuses startup. The server never looks for a config file in the working directory. The bundled file has no `api_key` setting, and none can be added.
