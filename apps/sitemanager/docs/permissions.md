# Permission System — Site Manager Server

Every tool on this server is read-only. The Site Manager API has no write operations, so there is nothing to confirm and nothing to gate.

- **Permission mode** (`UNIFI_TOOL_PERMISSION_MODE`) has no effect here: it governs mutations.
- **Policy gates** (`UNIFI_POLICY_*`) apply to `CREATE`, `UPDATE` and `DELETE` actions. This server has none. No policy variable, legacy permission variable or YAML setting adds a write tool.
- **Confirmation** does not apply. The nine tools run as soon as they are called; there is no preview-then-confirm step and no `confirm` argument.
- Every domain tool is annotated `readOnlyHint: true`, so clients that restrict themselves to read-only tools can call all of them.

## What controls access instead

The API key. A Site Manager key can read every console the account can see, and the server returns whatever the key allows. To narrow what the server can read, narrow the account or the key at [unifi.ui.com](https://unifi.ui.com). The server cannot narrow it for you.

To limit which tools are registered, use eager mode with `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS`. See [configuration.md](configuration.md#tool-categories). This changes what the client sees; it does not change what the key can read.

## Meta-tools and read-only clients

The meta-tools carry conservative annotations, because a dispatcher's hint has to hold for any tool it could run:

| Tool | `readOnlyHint` |
|---|---|
| `sitemanager_tool_index`, `sitemanager_batch_status` | `true` |
| `sitemanager_execute`, `sitemanager_batch`, `sitemanager_load_tools` | `false` |

A client that asks for approval before tools that are not read-only will ask before `sitemanager_execute` and `sitemanager_batch`, even though everything they can run here only reads. A client that allows only read-only tools cannot call them at all. That is why the default lazy mode lists all nine tools directly: call them by name and no approval for a dispatcher is needed. In `meta_only` mode the nine tools are reachable only through `sitemanager_execute`, so read-only-only clients reach nothing.

## Common scenarios

### No key yet

The server starts in setup mode and lists only `sitemanager_setup_status`, which is read-only and explains what to set. It makes no request to the API. See [configuration.md](configuration.md#the-api-key).

### Only inventory, no metrics or SD-WAN

```bash
UNIFI_TOOL_REGISTRATION_MODE=eager
UNIFI_ENABLED_CATEGORIES=hosts,sites,devices
```

### Serving HTTP to another machine

Every caller who reaches the endpoint reads with the same key. Set `UNIFI_SITEMANAGER_MCP_HTTP_AUTH_TOKEN`, keep the bind address on loopback behind a proxy you control, and list the proxy's host name in `UNIFI_MCP_ALLOWED_HOSTS`. See [configuration.md](configuration.md#http-transport).

## Response redaction

Responses pass through the same redaction as the other servers. Fields whose names mark them as secrets are replaced with `***REDACTED***` unless `UNIFI_SITEMANAGER_REDACT_SENSITIVE_FIELDS=false` (or the shared `UNIFI_REDACT_SENSITIVE_FIELDS=false`). Independently of that setting, the account holder's name, email and role are never returned, and a host's full reported state leaves out account identifiers, device location and image metadata.
