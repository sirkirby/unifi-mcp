# MCP Discovery and Lazy-Loading Meta-Tools

UniFi MCP follows the standard MCP tool discovery path first: clients discover
currently registered tools with `tools/list` and invoke them with `tools/call`.
The meta-tools support lazy loading through filtered discovery, indirect
execution, batch orchestration, and optional direct registration. They keep the
initial `tools/list` response small without changing the standard MCP path and
are unrelated to protocol-version response compatibility.

References:

- [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [2026 MCP roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/)

## Standard MCP Path

The canonical MCP discovery flow is:

1. Call `tools/list` to get the tools that are currently registered.
2. Call a returned tool by name with `tools/call`.
3. If the server sends `notifications/tools/list_changed`, call `tools/list`
   again to refresh the client-side catalog.

Use this path when the client supports the standard tool list well, especially
in `eager` mode where all selected domain tools are registered directly.

## Lazy-Loading Meta-Tool Path

Each app exposes the following lazy-loading meta-tools:

| App | Prefix | Meta-tools |
|-----|--------|------------|
| Network | `unifi_` | `unifi_tool_index`, `unifi_execute`, `unifi_batch`, `unifi_batch_status`, `unifi_batch_cancel`, `unifi_load_tools` in lazy mode |
| Protect | `protect_` | `protect_tool_index`, `protect_execute`, `protect_batch`, `protect_batch_status`, `protect_batch_cancel`, `protect_load_tools` in lazy mode |
| Access | `access_` | `access_tool_index`, `access_execute`, `access_batch`, `access_batch_status`, `access_batch_cancel`, `access_load_tools` in lazy mode |
| Site Manager | `sitemanager_` | `sitemanager_tool_index`, `sitemanager_execute`, `sitemanager_batch`, `sitemanager_batch_status`, `sitemanager_batch_cancel`, `sitemanager_load_tools` in lazy mode |
| InnerSpace | `innerspace_` | `innerspace_tool_index`, `innerspace_execute`, `innerspace_batch`, `innerspace_batch_status`, `innerspace_batch_cancel`, `innerspace_load_tools` in lazy mode |
| Drive | `drive_` | `drive_tool_index`, `drive_execute`, `drive_batch`, `drive_batch_status`, `drive_batch_cancel`, `drive_load_tools` in lazy mode |

These tools are not replacements for `tools/list`. They are UniFi-specific
extensions for clients and models that need a compact, filterable catalog or
need to execute tools that are not directly present in the current `tools/list`
response.

### Tool Index

In `lazy` mode, `*_tool_index` returns the full known catalog from the generated
manifest. In `eager` mode, it returns the registered runtime catalog. In
`meta_only` mode, it initially returns only the registered meta-tools. Domain
tools can still be called through `*_execute` when their names are already
known; that execution lazily registers the tool's module, so later index results
can include those loaded domain tools. By default the index returns compact name
and description entries. It can be filtered by `category` or `search`, and can
include input/output schemas with `include_schemas=true`.

Once you know a tool's name, use `name` to retrieve exactly that entry:

```json
{"name": "unifi_tool_index", "arguments": {"name": "unifi_list_clients", "include_schemas": true}}
```

`name` matches the complete, case-sensitive tool name. Unknown names, including
an empty string, return `tools: []` and `count: 0` in the usual index response.
Do not combine `name` with `category` or `search`; the index returns an error for
that combination, even when the other filter is an empty string. Omitting `name`
preserves the existing category and ranked-search behavior. In `meta_only` mode,
exact lookup covers the currently registered catalog; it does not load a domain
module. The same contract applies to Network, Protect, Access, and Site Manager,
including when their index tools are called through the relay.

Example:

```json
{"name": "unifi_tool_index", "arguments": {"category": "clients"}}
```

Use `*_tool_index` when:

- the client has a limited context window
- the server is in `lazy` mode
- the model needs searchable tool descriptions before choosing a tool
- a relay or sidecar needs a manifest-backed full catalog

### Execute and Batch

`*_execute` calls a named domain tool through the server's lazy loader. It is
the indirect execution path for clients that only see meta-tools in
`tools/list`.

Example:

```json
{
  "name": "unifi_execute",
  "arguments": {
    "tool": "unifi_list_clients",
    "arguments": {"limit": 50}
  }
}
```

`*_batch`, `*_batch_status` and `*_batch_cancel` provide the same indirect execution path
for several operations. Writes run one at a time in submission order; reads run
concurrently, up to a cap. `*_batch_status` reports a job waiting for an earlier
job or for its write turn as `queued`, with its `position` (the writes ahead of
it) once it is in the write queue, and a withdrawn job as `cancelled`.
`*_batch_cancel` withdraws jobs that are still queued; a running or finished job
is reported, not cancelled.
Direct tool calls take their turn at the same per-controller gate, so a batch and
a direct write never run at once. The guarantee is per server process; see each
server's configuration page for its `*_WRITE_HOLD_SECONDS`, `*_CALL_WAIT_SECONDS`
and `*_READ_CONCURRENCY` settings.

### Load Tools

`*_load_tools` is available in `lazy` mode for clients that want direct MCP
tool calls after discovering the catalog. It loads selected tools into the
standard `tools/list` surface and sends `notifications/tools/list_changed` when
one or more tools are loaded.

Flow:

1. Call `tools/list` and find `*_load_tools`.
2. Use `*_tool_index` to choose tool names.
3. Call `*_load_tools` with those names.
4. Wait for `notifications/tools/list_changed`.
5. Call `tools/list` again and then call the newly registered tools directly.

Clients that do not refresh their tool list after
`notifications/tools/list_changed` should use `*_execute` instead.

## Registration Modes

`UNIFI_TOOL_REGISTRATION_MODE` controls how much of the catalog is directly
registered with MCP.

| Mode | Initial `tools/list` behavior | Full catalog access | Best fit |
|------|-------------------------------|---------------------|----------|
| `eager` | Meta-tools plus all selected domain tools are registered directly | Standard `tools/list`; optional `*_tool_index` for compact filtering | Clients that handle large tool lists well, dev consoles, and parity checks |
| `lazy` (default) | Meta-tools plus `*_load_tools` are registered initially, with a few read-only domain tools listed directly (each app's `LAZY_DIRECT_TOOLS`) | `*_tool_index` plus `*_execute`, or `*_load_tools` followed by `tools/list` refresh | Production LLM clients with limited context |
| `meta_only` | Only the core meta-tools are registered and indexed initially; executed domain modules are then registered | `*_execute`/`*_batch` with already-known domain tool names | Maximum initial context control; clients that already know the domain tools they need |

### Site Manager differences

The Site Manager server has nine domain tools, all read-only, and it adjusts
the shared model in three ways:

- In `lazy` mode it lists all nine domain tools directly, not a few. Its
  dispatchers carry conservative annotations: `sitemanager_tool_index` and
  `sitemanager_batch_status` are marked read-only, while `sitemanager_execute`,
  `sitemanager_batch`, `sitemanager_batch_cancel` and `sitemanager_load_tools`
  are not, because a
  dispatcher's hint has to hold for any tool it could run. A client that allows
  only read-only tools can still call the nine tools by name.
- In `meta_only` mode the nine tools are reachable only through
  `sitemanager_execute`, so a client that allows only read-only tools reaches
  none of them.
- Without a key it starts in setup mode and registers only
  `sitemanager_setup_status`, which explains what to set and makes no request.

See [Site Manager permissions](../apps/sitemanager/docs/permissions.md#meta-tools-and-read-only-clients).

### InnerSpace differences

The InnerSpace server has nine domain tools, all read-only, and it adjusts the
shared model the same way Site Manager does:

- In `lazy` mode it lists all nine domain tools directly. `innerspace_tool_index`
  and `innerspace_batch_status` are marked read-only, while `innerspace_execute`,
  `innerspace_batch`, `innerspace_batch_cancel` and `innerspace_load_tools` are not, so the read-only
  guarantee covers the nine domain tools and not the meta-tools.
- In `meta_only` mode the nine tools are reachable only through
  `innerspace_execute`, so a client that allows only read-only tools reaches
  none of them.
- Without a host it starts in setup mode and registers only
  `innerspace_setup_status`, which explains what to set and makes no request.
- Its categories are `status`, `project`, `floor_plans` and `devices`, for
  `UNIFI_ENABLED_CATEGORIES` and the `category` filter of `innerspace_tool_index`.
- Its tool descriptions say that InnerSpace ids are scoped to the InnerSpace
  tool family and must not be passed to the other servers.

See [InnerSpace permissions](../apps/innerspace/docs/permissions.md#meta-tools-and-read-only-clients).

### Drive differences

The Drive server has 11 domain tools: seven reads and four writes that preview
before they change anything. It follows the shared model, with these points:

- In `lazy` mode it lists only the meta-tools, like Network, Protect and
  Access. The domain tools are reached through `drive_execute`, `drive_batch`
  or `drive_load_tools`.
- Without a host it starts in setup mode and registers only
  `drive_setup_status`, which explains what to set and makes no request. With
  a host it still makes no request at startup: the first tool call logs in.
- Its tool modules are `system`, `storage`, `shared_drives`, `file_services`
  and `nfs`, for `UNIFI_ENABLED_CATEGORIES` and the `category` filter of
  `drive_tool_index`.

See [Drive permissions](../apps/drive/docs/permissions.md).

Standard MCP-only clients remain supported in `eager` mode. In `lazy` and
`meta_only` modes, `tools/list` is still correct: it reports the tools currently
registered with the server. The UniFi extension path exposes the larger
manifest-backed catalog in `lazy` mode; `meta_only` starts both direct discovery
surfaces with meta-tools and expands them only as known domain modules execute.

## Implementation Notes

- Shared meta-tool registration lives in
  `packages/unifi-mcp-shared/src/unifi_mcp_shared/meta_tools.py`.
- Registration mode dispatch lives in
  `packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_registration.py`.
- Lazy loading lives in
  `packages/unifi-mcp-shared/src/unifi_mcp_shared/lazy_tools.py`.
- Generated manifests live in each app package as `tools_manifest.json` and are
  regenerated with `make manifest`.
- The generated manifest is the source for compact discovery in `lazy` mode;
  direct MCP `tools/list` remains the source for currently registered tools.

## Extension Guidance

Prefer the standard MCP path whenever it is enough. Add or depend on UniFi
extensions only when they solve a concrete catalog-size, lazy-loading, or relay
workflow constraint.

If you are building a custom application, code-execution runtime, or MCP adapter
that needs dependent calls, joins, loops, or branching, build it against
[`unifi-api-server`](../apps/api/README.md). Use GraphQL for field-selective
reads, REST for typed resource reads, `POST /v1/actions/{tool_name}` for
supported operations, and SSE for live events. An MCP adapter can expose tools
to its clients while using the API as its backend. The calling application must
sandbox generated code and enforce its resource limits. Existing MCP clients
can continue to process tool results in client-side code.

When adopting new MCP spec features:

- keep `tools/list` and `tools/call` behavior standard
- preserve `notifications/tools/list_changed` after direct lazy loading
- map future standard metadata surfaces to the generated manifest before adding
  new bespoke discovery APIs
- keep OAuth and remote exposure concerns scoped to relay/cloud deployments;
  the Network, Protect, Access, InnerSpace and Drive servers continue to target
  local console access, and the Site Manager server targets only Ubiquiti's fixed
  `api.ui.com` origin
