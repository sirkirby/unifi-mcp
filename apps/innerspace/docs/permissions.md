# Permission System — InnerSpace Server

The nine domain tools only read. The InnerSpace server registers no write tool, so there is nothing to confirm and nothing to gate.

- **Permission mode** (`UNIFI_TOOL_PERMISSION_MODE`) has no effect here: it governs mutations.
- **Policy gates** (`UNIFI_POLICY_*`) apply to `CREATE`, `UPDATE` and `DELETE` actions. This server has none in this version, and no policy variable or YAML setting adds a write tool.
- **Confirmation** does not apply. The nine tools run as soon as they are called; there is no preview-then-confirm step and no `confirm` argument.
- Each domain tool is annotated `readOnlyHint: true`, `idempotentHint: true` and `openWorldHint: false`, so clients that restrict themselves to read-only tools can call all nine.

The guarantee covers the nine domain tools. The meta-tools are dispatchers and are not counted as read-only tools; see [below](#meta-tools-and-read-only-clients).

## What controls access instead

The console account. The server logs in with the username and password you give it and returns whatever that account can read in InnerSpace. To narrow what the server can read, use a console account with only the access it needs. The server cannot narrow it for you, and it needs an account that can open the InnerSpace application, for example a Super Admin. A console that refuses the session for InnerSpace is reported as an access error, not as a missing application; see [troubleshooting](troubleshooting.md#the-console-refused-the-session-for-innerspace).

There is no API key path: a console's local `UNIFI_API_KEY` is never used for InnerSpace.

To limit which tools are registered, use eager mode with `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS`. See [configuration.md](configuration.md#tool-categories). This changes what the client sees; it does not change what the account can read. The plan image resource follows `innerspace_get_plan_asset`: a filter that leaves that tool out leaves the resource unregistered too.

## Meta-tools and read-only clients

The meta-tools carry conservative annotations, because a dispatcher's hint has to hold for any tool it could run:

| Tool | `readOnlyHint` |
|---|---|
| `innerspace_tool_index`, `innerspace_batch_status` | `true` |
| `innerspace_execute`, `innerspace_batch`, `innerspace_batch_cancel`, `innerspace_load_tools` | `false` |

A client that asks for approval before tools that are not read-only will ask before `innerspace_execute` and `innerspace_batch`, even though the only tools they can run here read. A client that allows only read-only tools cannot call them at all. That is why the default lazy mode lists all nine domain tools directly: call them by name and no approval for a dispatcher is needed. In `meta_only` mode the nine tools are reachable only through `innerspace_execute`, so a read-only-only client reaches nothing.

## Common scenarios

### No host yet

The server starts in setup mode and lists only `innerspace_setup_status`, which is read-only and explains what to set. It makes no request to the console. See [configuration.md](configuration.md#the-console-login).

### Only status and floor plans

```bash
UNIFI_TOOL_REGISTRATION_MODE=eager
UNIFI_ENABLED_CATEGORIES=status,floor_plans
```

### Serving HTTP to another machine

Every caller who reaches the endpoint reads with the same console login. Set `UNIFI_INNERSPACE_MCP_HTTP_AUTH_TOKEN`, keep the bind address on loopback behind a proxy you control, and list the proxy's host name in `UNIFI_MCP_ALLOWED_HOSTS`. See [configuration.md](configuration.md#http-transport).

## Response redaction

Responses pass through the same redaction as the other servers. Fields whose names mark them as secrets (passwords, tokens, keys and similar) are redacted by default and come back as `***REDACTED***`. Set `UNIFI_INNERSPACE_REDACT_SENSITIVE_FIELDS=false` (or the shared `UNIFI_REDACT_SENSITIVE_FIELDS=false`) only for a trusted local process that needs raw values.

Redaction matches field names, not meaning. MAC addresses are not redacted, and neither are serial numbers, device and plan names or the geometry of a plan. A floor plan describes a building, so treat the whole result as sensitive and review it before sharing.

The plan image returned by `innerspace_get_plan_asset` with `include_image` is binary data, not a field, and is not covered by redaction. Read the image only where you would show the floor plan itself.
