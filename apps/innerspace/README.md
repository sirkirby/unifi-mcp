<!-- mcp-name: io.github.sirkirby/unifi-innerspace-mcp -->
# UniFi InnerSpace MCP Server

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server for UniFi InnerSpace, the floor-plan application that runs on a UniFi OS console. It is not yet released: there is no published package, image or plugin, and the tool set is still being added.

## How it connects

InnerSpace is a separate application on the console, served under `/proxy/innerspace/`. This server logs in to the console with a username and password and reads through that session. There is no API key setting: InnerSpace has no key path here, and a console's local `UNIFI_API_KEY` is never read or sent.

## Configure

Set these variables in the server's process environment. The server does not load `.env` files from the working directory.

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_INNERSPACE_HOST` (or `UNIFI_HOST`) | none | Console address. Without it the server starts in setup mode and makes no request. |
| `UNIFI_INNERSPACE_USERNAME`, `UNIFI_INNERSPACE_PASSWORD` | none | Console login. `_FILE` and `_COMMAND` forms follow the shared [credential provider](../../docs/credential-providers.md) rules. |
| `UNIFI_INNERSPACE_PORT` | `443` | Console HTTPS port. |
| `UNIFI_INNERSPACE_VERIFY_SSL` | `false` | Verify the console certificate. |
| `UNIFI_INNERSPACE_SSL_FINGERPRINT` (or `UNIFI_SSL_FINGERPRINT`) | none | Pin the console certificate by SHA-256 fingerprint. |
| `UNIFI_INNERSPACE_REDACT_SENSITIVE_FIELDS` | `true` | Redact secret-looking fields in responses. |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | `lazy`, `eager` or `meta_only`. |

With certificate checks off, the server logs one warning at its first connection.

HTTP is opt-in, listens on port 3005 by default, and takes a bearer token from `UNIFI_INNERSPACE_MCP_HTTP_AUTH_TOKEN` (or its `_FILE` form).

## Scope

Every domain tool will read only. The server has no write tools, support bundle, events or websocket.
