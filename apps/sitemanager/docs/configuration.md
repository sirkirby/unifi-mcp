# Configuration — Site Manager Server

## The API key

Create a key at [unifi.ui.com](https://unifi.ui.com) under Settings > API Keys, then give it to the server in one of these ways:

| Variable | Use |
|---|---|
| `UNIFI_SITEMANAGER_API_KEY` | The key itself |
| `UNIFI_SITEMANAGER_API_KEY_FILE` | Path to a file holding the key |
| `UNIFI_SITEMANAGER_API_KEY_COMMAND` | A command that prints the key |

The key is read from these variables and nowhere else:

- Not from `UNIFI_API_KEY`. That variable holds a console's local key, which must never be sent to the cloud.
- Not from `config.yaml` or a `CONFIG_PATH` file.

Without a key the server starts in setup mode: it answers the client, explains what to set, and makes no request.

The key covers every console the account can see. Treat it accordingly.

## Destination

Requests go to `https://api.ui.com`. This is fixed and cannot be changed by configuration. The server does not follow redirects and ignores proxy environment variables.

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_SITEMANAGER_TIMEOUT_SECONDS` | `30` | Seconds to wait for one API response |
| `UNIFI_SITEMANAGER_REDACT_SENSITIVE_FIELDS` | `true` | Redact secret-looking fields in responses (falls back to `UNIFI_REDACT_SENSITIVE_FIELDS`) |
| `UNIFI_SITEMANAGER_MCP_CONTENT_MODE` | `adaptive` | MCP response content mode (falls back to `UNIFI_MCP_CONTENT_MODE`) |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | `lazy`, `eager` or `meta_only` |
| `UNIFI_ENABLED_CATEGORIES` | all | Eager mode only: `hosts`, `sites`, `devices`, `isp_metrics`, `sdwan` |
| `UNIFI_ENABLED_TOOLS` | all | Eager mode only: specific tool names |
| `UNIFI_MCP_LOG_LEVEL` | `INFO` | Log level (logs go to stderr) |
| `UNIFI_SETTINGS_FILE` | none | Per-user settings file, such as `~/.config/unifi-mcp/sitemanager.env` |

## HTTP transport

Stdio is the default. To serve HTTP:

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_MCP_HTTP_ENABLED` | `false` | Serve HTTP as well as stdio |
| `UNIFI_MCP_HOST` | `127.0.0.1` | Bind address |
| `UNIFI_MCP_PORT` | `3003` | Port |
| `UNIFI_MCP_HTTP_TRANSPORT` | `streamable-http` | `streamable-http` or `sse` |
| `UNIFI_SITEMANAGER_MCP_HTTP_AUTH_TOKEN` | none | Bearer token every request must carry (falls back to `UNIFI_MCP_HTTP_AUTH_TOKEN`) |

Anyone who can reach the HTTP endpoint can read the whole account's inventory. Keep it on loopback or set an auth token.

## Registration modes

| Mode | What the client sees |
|---|---|
| `lazy` (default) | The meta-tools and all nine tools |
| `eager` | The meta-tools except `sitemanager_load_tools`, and all nine tools |
| `meta_only` | The meta-tools only; reach tools through `sitemanager_execute` |

Lazy mode lists every tool directly because `sitemanager_execute` is not marked read-only, and a client that permits only read-only tools would otherwise reach nothing.
