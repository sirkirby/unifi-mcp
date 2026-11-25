# Configuration — Drive Server

Configuration comes from the server's process environment. The server never loads a `.env` file from the working directory. To keep settings out of a client's config file, load a trusted env file in your launcher (for example Docker `env_file:`), or name a per-user settings file with an absolute `UNIFI_SETTINGS_FILE` path.

## The NAS login

A UniFi NAS (UNAS Pro, UNAS Pro 8 and similar) is its own UniFi OS console. It is not part of the gateway and is not reachable through the Network application. Point this server at the NAS and log in with a **local** UniFi OS account on it. A UI.com account with MFA cannot log in here. There is no API key setting.

| Variable | Use |
|---|---|
| `UNIFI_DRIVE_HOST` | IP address or hostname of the NAS |
| `UNIFI_DRIVE_USERNAME` | Local UniFi OS username on the NAS |
| `UNIFI_DRIVE_PASSWORD` | Its password; `UNIFI_DRIVE_PASSWORD_FILE` and `UNIFI_DRIVE_PASSWORD_COMMAND` work too (set one) |
| `UNIFI_DRIVE_PORT` | HTTPS port of the NAS, default `443` |

**No shared fallback.** `UNIFI_HOST`, `UNIFI_PORT`, `UNIFI_USERNAME` and `UNIFI_PASSWORD` name the gateway, so this server never reads them, and it never sends the NAS login to any other host. Set the four `UNIFI_DRIVE_*` values even when the NAS uses the same account name as the gateway. The `_FILE` and `_COMMAND` forms follow the shared [credential provider](../../../docs/credential-providers.md) rules.

The account needs access to UniFi Drive. Reads work for an account that can open Drive; turning file services on or off and changing NFS clients need an administrator of Drive. A request the account may not make returns a 403 error that says so.

Without a host the server starts in setup mode: it answers the client, offers only `drive_setup_status`, explains what to set, and makes no request. With a host it also makes no request at startup. The first tool call logs in, and a session that expires is logged in again once. A rejected login pauses further logins for 60 seconds, doubling with each rejection up to 15 minutes, so repeated tool calls cannot lock the account out.

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_DRIVE_VERIFY_SSL` | `false` | Verify the NAS certificate against the system's trusted CAs (falls back to `UNIFI_VERIFY_SSL`) |
| `UNIFI_DRIVE_SSL_FINGERPRINT` | none | Pin the NAS certificate by SHA-256 fingerprint; no shared fallback |
| `UNIFI_DRIVE_TIMEOUT_SECONDS` | `30` | Seconds to wait for one response from the NAS |
| `UNIFI_DRIVE_TOOL_PERMISSION_MODE` | `confirm` | `bypass` skips the write previews (falls back to `UNIFI_TOOL_PERMISSION_MODE`); see [Permissions](permissions.md) |
| `UNIFI_DRIVE_READ_ONLY` | `false` | `true` refuses every write, whatever the policy gates say (falls back to `UNIFI_READ_ONLY`) |
| `UNIFI_DRIVE_REQUIRE_PREVIEW_TOKEN` | `false` | `true` makes `confirm=true` carry the token from its preview (falls back to `UNIFI_REQUIRE_PREVIEW_TOKEN`) |
| `UNIFI_POLICY_DRIVE_*` | allowed | Policy gates that switch writes off; see [Permissions](permissions.md#policy-gates) |
| `UNIFI_DRIVE_REDACT_SENSITIVE_FIELDS` | `true` | Redact secret-looking fields in responses (falls back to `UNIFI_REDACT_SENSITIVE_FIELDS`) |
| `UNIFI_DRIVE_MCP_CONTENT_MODE` | `adaptive` | MCP response content mode (falls back to `UNIFI_MCP_CONTENT_MODE`) |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | `lazy`, `eager` or `meta_only` |
| `UNIFI_ENABLED_CATEGORIES` | all | Eager mode only: see [Tool categories](#tool-categories) |
| `UNIFI_ENABLED_TOOLS` | all | Eager mode only: specific tool names |
| `UNIFI_MCP_LOG_LEVEL` | `INFO` | Log level (logs go to stderr) |
| `UNIFI_SETTINGS_FILE` | none | Per-user settings file of `KEY=value` lines, applied before configuration is read |

Settings are read once at startup. Restart the server, or start a new client session, after changing any of them. There are no event or websocket settings: Drive has no event stream here.

## NAS operation gate

Every tool call takes a slot at this server's operation gate for the NAS before it reaches the NAS. Reads run side by side up to a cap; confirmed writes run one at a time, in the order they arrive (direct calls, `drive_execute` and `drive_batch` alike). The guarantee is per server process: two servers, or two copies of one, pointed at the same NAS do not coordinate, and neither does the Drive web app. Unlike the connection settings, these fall back to the shared `UNIFI_*` value, because they tune this process rather than name a console.

| Variable | Default | Description |
|----------|---------|-------------|
| `UNIFI_DRIVE_WRITE_HOLD_SECONDS` / `UNIFI_WRITE_HOLD_SECONDS` | `120` | How long one write may hold its turn (10 to 3600). Once it has held longer, calls queued behind it are refused as busy, with nothing sent; a write's own requests to the NAS stop at this budget. |
| `UNIFI_DRIVE_CALL_WAIT_SECONDS` / `UNIFI_CALL_WAIT_SECONDS` | `25` | How long a direct tool call waits for its turn before it is refused as busy (1 to 3600). Batch jobs wait as long as the queue keeps moving. |
| `UNIFI_DRIVE_READ_CONCURRENCY` / `UNIFI_READ_CONCURRENCY` | `8` | Reads that may run at once (1 to 64). |

A value that is not a number in range stops the server at startup, naming the variable. A call refused as busy returns `success: false` with the reason, plus `mutation_applied: false` for a confirmed write; nothing is sent to the NAS. A confirmed write whose budget runs out before its change is sent also returns `mutation_applied: false`; one cut off after the change was sent, or never answered, returns `mutation_applied: null`, and the NAS should be read back before retrying.

## TLS

A NAS usually presents a self-signed certificate, so verification is off by default. Choose one of:

- Pin the certificate: set `UNIFI_DRIVE_SSL_FINGERPRINT` to the NAS certificate's SHA-256 fingerprint. A pin overrides `UNIFI_DRIVE_VERIFY_SSL`. The shared `UNIFI_SSL_FINGERPRINT` pins the gateway's certificate and is never used for the NAS. A malformed pin stops the server at startup with a log line that does not repeat the value.
- Verify against trusted CAs: set `UNIFI_DRIVE_VERIFY_SSL=true`.

With neither, and a host set, the server logs one warning at startup that the NAS certificate is not checked. See [TLS verification](../../../docs/tls-verification.md) for how to read a fingerprint.

The session client never follows redirects and ignores proxy environment variables, so the session cookie cannot be sent anywhere but the NAS you named.

## MCP response content

`UNIFI_DRIVE_MCP_CONTENT_MODE` (falling back to `UNIFI_MCP_CONTENT_MODE`) controls how tool results are returned to the client.

| Mode | What the client gets |
|---|---|
| `adaptive` (default) | Decided per request from the MCP `protocolVersion` the client advertised during initialization, not from the client's name. `2025-06-18` or later: a short `content` text plus the full result once in `structuredContent`. Earlier, missing or malformed revisions: the full JSON in `content`. |
| `compat` | Always the full JSON in `content`. |
| `compact` | Always the short text plus the full result in `structuredContent`. |

The meta-tools (`drive_tool_index`, `drive_execute`, `drive_batch`, `drive_batch_status`, `drive_batch_cancel` and `drive_load_tools`) return their result in `content` in every mode.

## HTTP transport

Stdio is the default. To serve HTTP:

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_MCP_HTTP_ENABLED` | `false` | Serve HTTP as well as stdio |
| `UNIFI_MCP_HOST` | `127.0.0.1` | Bind address |
| `UNIFI_MCP_PORT` | `3004` | Port |
| `UNIFI_MCP_HTTP_TRANSPORT` | `streamable-http` | `streamable-http` or `sse` |
| `UNIFI_DRIVE_MCP_HTTP_AUTH_TOKEN` | none | Bearer token every request must carry (falls back to `UNIFI_MCP_HTTP_AUTH_TOKEN`) |
| `UNIFI_DRIVE_MCP_HTTP_AUTH_TRUSTED_NETWORKS` | none | IP addresses or CIDR networks whose requests skip the bearer token: the pinned address of an authenticating proxy, never a whole container network. Falls back to `UNIFI_MCP_HTTP_AUTH_TRUSTED_NETWORKS`; empty turns the exemption off. Docker Compose passes only this server-level spelling. See [Trusted networks](../../network/docs/transports.md#trusted-networks) |
| `UNIFI_MCP_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host headers the server accepts, comma-separated (for a reverse proxy) |
| `UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION` | `true` | Check the Host header against `UNIFI_MCP_ALLOWED_HOSTS` |
| `UNIFI_MCP_HTTP_FORCE` | `false` | Serve HTTP from a process that is not PID 1 (local development only) |
| `UNIFI_MCP_STDIO_ENABLED` | `true` | Set `false` to serve HTTP alone from a process that is not PID 1 (an init-managed container or a service manager); needs `UNIFI_MCP_HTTP_ENABLED=true` and `UNIFI_MCP_HTTP_FORCE=true` |

Anyone who can reach the HTTP endpoint can read the NAS's storage layout and call the write tools with the server's login. Keep it on loopback or set an auth token. The token is resolved in this order: `UNIFI_DRIVE_MCP_HTTP_AUTH_TOKEN`, then `UNIFI_MCP_HTTP_AUTH_TOKEN`, then `server.http.auth_token` in a `CONFIG_PATH` file; both variables accept the `_FILE` and `_COMMAND` forms. A token that is set but empty, shorter than 32 characters, or holding whitespace refuses startup rather than turning authentication off.

HTTP binds only in the container's main process (PID 1). Started any other way with `UNIFI_MCP_HTTP_ENABLED=true`, the server logs that HTTP was skipped and serves stdio only, unless `UNIFI_MCP_HTTP_FORCE=true`. Outside PID 1, stdio stays the primary transport; `UNIFI_MCP_STDIO_ENABLED=false` serves HTTP alone. Never set these variables in a client's MCP entry.

### Docker Compose

The `unifi-drive-mcp` service in `docker/docker-compose.yml` is in the opt-in `drive` profile, so it does not start with the default stack. The Compose service builds the image from this checkout; the published image is `ghcr.io/sirkirby/unifi-drive-mcp`.

```bash
export UNIFI_DRIVE_HOST=192.168.1.20
export UNIFI_DRIVE_USERNAME=mcp
export UNIFI_DRIVE_PASSWORD="$(cat "$HOME/.config/unifi-mcp/drive-password")"
export UNIFI_DRIVE_MCP_HTTP_AUTH_TOKEN="$(cat "$HOME/.config/unifi-mcp/drive-http-token")"
docker compose -f docker/docker-compose.yml --profile drive up --build unifi-drive-mcp
```

The example passes the password itself because the service mounts no files: a `_FILE` path is read inside the container, so `UNIFI_DRIVE_PASSWORD_FILE` works only with a read-only mount you add in an override file, for example `docker/docker-compose.override.yml`:

```yaml
services:
  unifi-drive-mcp:
    volumes:
      - ${HOME}/.config/unifi-mcp/drive-password:/run/secrets/drive-password:ro
    environment:
      - UNIFI_DRIVE_PASSWORD_FILE=/run/secrets/drive-password
      - UNIFI_POLICY_DRIVE_NFS_CONNECTIONS_DELETE=false
```

Policy gates and the permission mode go in the same override file: the service passes only its connection and HTTP variables.

The service listens on `0.0.0.0:3004` inside the container and is published only on `127.0.0.1:3004` on the host. Other containers on the Compose network can reach it, so set the bearer token before relying on it: the service passes the token variables through only when they are set in your shell, and it does not generate one. It receives only its own `UNIFI_DRIVE_*` connection variables (and the HTTP token variables), never the shared `.env` file the other services load, and it is not in the relay's default server list. Compose takes those values from your shell, from `docker/.env`, or from a file named with `--env-file`. An unset port or `UNIFI_DRIVE_VERIFY_SSL` takes the server's default.

## Diagnostics

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_MCP_DIAGNOSTICS` | `false` | Log one line per tool call: tool name, duration, success, and the exception class on failure |
| `UNIFI_MCP_DIAG_LOG_TOOL_ARGS` | `true` | Accepted for compatibility; arguments are never logged |
| `UNIFI_MCP_DIAG_LOG_TOOL_RESULT` | `true` | Accepted for compatibility; results are never logged |
| `UNIFI_MCP_DIAG_MAX_PAYLOAD` | `2000` | Maximum characters of one diagnostic line |

Error text never contains the NAS address or the credentials: it names the request's method, path and HTTP status, plus Drive's own error message, length-capped and with the NAS address removed. There is no support-bundle tool on this server; see [Troubleshooting](troubleshooting.md#reporting-a-problem).

## Tracing

The MCP SDK records a span for every MCP message. Setting an OTLP endpoint exports them. The Docker image includes the exporter; a pip or uvx install needs the `otel` extra (`unifi-drive-mcp[otel]`), and a source checkout can add it with `uv sync --extra otel --package unifi-drive-mcp`.

| Variable | Default | Purpose |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP collector endpoint; spans are exported only when this or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set |
| `OTEL_SERVICE_NAME` | `unifi-drive-mcp` | Service name on exported spans |
| `OTEL_SDK_DISABLED` | `false` | `true` turns export off |

A span records the MCP method, the tool name, the JSON-RPC request id and the timing, not tool arguments or results.

## Tool categories

For `UNIFI_ENABLED_CATEGORIES` in eager mode, and the `category` filter of `drive_tool_index`:

| Category | Tools |
|---|---|
| `system` | `drive_get_system_info` |
| `storage` | `drive_list_storage_pools`, `drive_list_disks` |
| `shared_drives` | `drive_list_shared_drives`, `drive_get_shared_drive` |
| `file_services` | `drive_get_file_services`, `drive_set_file_service` |
| `nfs` | `drive_list_nfs_connections`, `drive_add_nfs_connection`, `drive_update_nfs_connection`, `drive_remove_nfs_connection` |

```bash
UNIFI_TOOL_REGISTRATION_MODE=eager UNIFI_ENABLED_CATEGORIES=system,storage
```

These are the tool module names. The policy gate categories are different: `file_services` and `nfs_connections` (see [Permissions](permissions.md#policy-gates)).

## Registration modes

| Mode | What the client sees |
|---|---|
| `lazy` (default) | The meta-tools; domain tools are reached through `drive_execute` or loaded with `drive_load_tools` |
| `eager` | The meta-tools except `drive_load_tools`, and all 11 tools (or the enabled subset) |
| `meta_only` | The meta-tools only; reach tools through `drive_execute` |

See [MCP discovery and meta-tools](../../../docs/tool-index.md).

## YAML config

The bundled `config.yaml` holds the NAS connection settings, server, HTTP, diagnostics and response policy. Each value can be set by the environment variable named above. To replace the file, set `CONFIG_PATH` to the absolute path of a YAML file you control; a relative path or a missing file refuses startup. The server never looks for a config file in the working directory. The bundled file has no `api_key` setting.
