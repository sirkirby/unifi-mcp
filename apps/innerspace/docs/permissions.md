# Permission System — InnerSpace Server

The server has nine read tools and 15 write tools. The reads need no permission. The writes change the InnerSpace layout of the console (walls, wall types, attenuation objects and their types, floor plan settings and the project unit) and go through the same permission system as the Network, Protect and Access servers.

- **Confirmation.** Every write previews first: `confirm=false` (the default) returns a preview and sends nothing, `confirm=true` applies. `UNIFI_INNERSPACE_TOOL_PERMISSION_MODE=bypass` (or the shared `UNIFI_TOOL_PERMISSION_MODE=bypass`) skips the preview. Preview tokens (`UNIFI_INNERSPACE_REQUIRE_PREVIEW_TOKEN=true`) make `confirm=true` follow a preview of the same arguments.
- **Policy gates.** `UNIFI_POLICY_INNERSPACE_<CATEGORY>_<ACTION>`, then `UNIFI_POLICY_INNERSPACE_<ACTION>`, then `UNIFI_POLICY_<ACTION>`; the most specific one set wins. A gate set to `false` blocks the tool's preview as well as its confirm. A misspelt `UNIFI_POLICY_INNERSPACE_*` name is reported in the log at startup.
- **Read-only mode.** `UNIFI_INNERSPACE_READ_ONLY=true` (or `UNIFI_READ_ONLY=true`) denies every write, previews included, whatever the gates say. The reads keep working.
- **Annotations.** Each read is annotated `readOnlyHint: true`, `idempotentHint: true` and `openWorldHint: false`. Each write has `readOnlyHint: false`; removals and the scale replacement also have `destructiveHint: true`.

| Category | `CREATE` | `UPDATE` | `DELETE` |
|---|---|---|---|
| `WALLS` | `innerspace_create_walls` | `innerspace_update_walls` | `innerspace_remove_walls` |
| `WALL_TYPES` | `innerspace_create_wall_type` | `innerspace_update_wall_type` | |
| `ATTENUATION` | `innerspace_create_attenuation_objects`, `innerspace_create_attenuation_object_type` | `innerspace_update_attenuation_objects`, `innerspace_update_attenuation_object_type` | `innerspace_remove_attenuation_objects` |
| `FLOOR_PLANS` | | `innerspace_rename_floor_plan`, `innerspace_set_floor_attenuation`, `innerspace_reorder_floor_plans` | `innerspace_set_plan_scale` |
| `PROJECT` | | `innerspace_set_project_unit` | |

For example, `UNIFI_POLICY_INNERSPACE_WALLS_DELETE=false` blocks `innerspace_remove_walls` only. `innerspace_set_plan_scale` is gated as a delete because it replaces the plan's scale line and every length on the plan depends on it.

[`unifi-api-server`](../../api/README.md#writing-innerspace) applies the same gates and read-only mode to its InnerSpace write actions, previews included.

Writes also refuse on their own, before anything is sent, when InnerSpace is not installed or not running on the console; see [tools.md](tools.md#writes).

The meta-tools are dispatchers and are not counted as read-only tools; see [below](#meta-tools-and-read-only-clients).

## What controls access instead

The console account. The server logs in with the username and password you give it, returns whatever that account can read in InnerSpace and, on a confirmed write, changes what that account can change. To narrow what the server can read, use a console account with only the access it needs. The server cannot narrow it for you, and it needs an account that can open the InnerSpace application, for example a Super Admin. A console that refuses the session for InnerSpace is reported as an access error, not as a missing application; see [troubleshooting](troubleshooting.md#the-console-refused-the-session-for-innerspace).

There is no API key path: a console's local `UNIFI_API_KEY` is never used for InnerSpace.

To limit which tools are registered, use eager mode with `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS`. See [configuration.md](configuration.md#tool-categories). This changes what the client sees; it does not change what the account can read or write. To keep the tools listed but refuse every change, use read-only mode instead. The plan image resource follows `innerspace_get_plan_asset`: a filter that leaves that tool out leaves the resource unregistered too.

## Meta-tools and read-only clients

The meta-tools carry conservative annotations, because a dispatcher's hint has to hold for any tool it could run:

| Tool | `readOnlyHint` |
|---|---|
| `innerspace_tool_index`, `innerspace_batch_status` | `true` |
| `innerspace_execute`, `innerspace_batch`, `innerspace_batch_cancel`, `innerspace_load_tools` | `false` |

A client that asks for approval before tools that are not read-only will ask before `innerspace_execute` and `innerspace_batch`. A client that allows only read-only tools cannot call them at all. That is why the default lazy mode lists the nine read tools directly: call them by name and no approval for a dispatcher is needed. The 15 write tools are not listed directly in lazy mode; reach them through `innerspace_execute` (or list them with `innerspace_load_tools`), where the client's approval for the dispatcher applies. In `meta_only` mode the domain tools are reachable only through `innerspace_execute`, so a client that allows only read-only tools reaches nothing.

## Common scenarios

### No host yet

The server starts in setup mode and lists only `innerspace_setup_status`, which is read-only and explains what to set. It makes no request to the console. See [configuration.md](configuration.md#the-console-login).

### Reads only

```bash
UNIFI_INNERSPACE_READ_ONLY=true
```

### Change the layout, but never remove anything or replace a scale

```bash
UNIFI_POLICY_INNERSPACE_DELETE=false
```

### Only status and floor plans

```bash
UNIFI_TOOL_REGISTRATION_MODE=eager
UNIFI_ENABLED_CATEGORIES=status,floor_plans
```

`floor_plans` includes the floor plan writes; add `UNIFI_INNERSPACE_READ_ONLY=true` to keep them from changing anything.

### Serving HTTP to another machine

Every caller who reaches the endpoint reads, and with confirmation writes, with the same console login. Set `UNIFI_INNERSPACE_MCP_HTTP_AUTH_TOKEN`, keep the bind address on loopback behind a proxy you control, and list the proxy's host name in `UNIFI_MCP_ALLOWED_HOSTS`. See [configuration.md](configuration.md#http-transport).

## Response redaction

Responses pass through the same redaction as the other servers. Fields whose names mark them as secrets (passwords, tokens, keys and similar) are redacted by default and come back as `***REDACTED***`. Set `UNIFI_INNERSPACE_REDACT_SENSITIVE_FIELDS=false` (or the shared `UNIFI_REDACT_SENSITIVE_FIELDS=false`) only for a trusted local process that needs raw values.

Redaction matches field names, not meaning. MAC addresses are not redacted, and neither are serial numbers, device and plan names or the geometry of a plan. A floor plan describes a building, so treat the whole result as sensitive and review it before sharing.

The plan image served by the plan image resources is binary data, not a field, and is not covered by redaction. Read the image only where you would show the floor plan itself.
