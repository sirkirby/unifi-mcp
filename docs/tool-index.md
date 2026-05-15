# MCP Discovery and UniFi Meta-Tools

UniFi MCP follows the standard MCP tool discovery path first: clients discover
currently registered tools with `tools/list` and invoke them with `tools/call`.
The UniFi meta-tools are compatibility and UX extensions layered on top of that
standard path. They keep large UniFi tool catalogs usable in constrained LLM
contexts, especially when lazy loading is enabled.

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

## UniFi Extension Path

Each app also exposes a small set of meta-tools:

| App | Prefix | Meta-tools |
|-----|--------|------------|
| Network | `unifi_` | `unifi_tool_index`, `unifi_execute`, `unifi_batch`, `unifi_batch_status`, `unifi_load_tools` in lazy mode |
| Protect | `protect_` | `protect_tool_index`, `protect_execute`, `protect_batch`, `protect_batch_status`, `protect_load_tools` in lazy mode |
| Access | `access_` | `access_tool_index`, `access_execute`, `access_batch`, `access_batch_status`, `access_load_tools` in lazy mode |

These tools are not replacements for `tools/list`. They are UniFi-specific
extensions for clients and models that need a compact, filterable catalog or
need to execute tools that are not directly present in the current `tools/list`
response.

### Tool Index

`*_tool_index` returns the full known catalog from the generated manifest or
runtime registry. By default it returns compact name and description entries.
It can be filtered by `category` or `search`, and can include input/output
schemas with `include_schemas=true`.

Example:

```json
{"name": "unifi_tool_index", "arguments": {"category": "clients"}}
```

Use `*_tool_index` when:

- the client has a limited context window
- the server is in `lazy` or `meta_only` mode
- the model needs searchable tool descriptions before choosing a tool
- a relay or sidecar needs a manifest-backed full catalog

### Execute and Batch

`*_execute` calls a named domain tool through the server's lazy loader. It is
the compatibility path for clients that only see meta-tools in `tools/list`.

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

`*_batch` and `*_batch_status` provide the same compatibility layer for multiple
parallel operations.

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
| `eager` | Meta-tools plus all selected domain tools are registered directly | Standard `tools/list`; optional `*_tool_index` for compact filtering | Clients that handle large tool lists well, dev consoles, compatibility checks |
| `lazy` (default) | Meta-tools plus `*_load_tools` are registered initially | `*_tool_index` plus `*_execute`, or `*_load_tools` followed by `tools/list` refresh | Production LLM clients with limited context |
| `meta_only` | Only the core meta-tools are registered initially | `*_tool_index` plus `*_execute`/`*_batch` | Maximum context control; clients that do not need direct domain tools |

Standard MCP-only clients remain supported in `eager` mode. In `lazy` and
`meta_only` modes, `tools/list` is still correct: it reports the tools currently
registered with the server, while the UniFi extension path exposes the larger
manifest-backed catalog.

## Implementation Notes

- Shared meta-tool registration lives in
  `packages/unifi-mcp-shared/src/unifi_mcp_shared/meta_tools.py`.
- Registration mode dispatch lives in
  `packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_registration.py`.
- Lazy loading lives in
  `packages/unifi-mcp-shared/src/unifi_mcp_shared/lazy_tools.py`.
- Generated manifests live in each app package as `tools_manifest.json` and are
  regenerated with `make manifest`.
- The generated manifest is the source for compact discovery in lazy/meta-only
  mode; direct MCP `tools/list` remains the source for currently registered
  tools.

## Compatibility Guidance

Prefer the standard MCP path whenever it is enough. Add or depend on UniFi
extensions only when they solve a concrete catalog-size, lazy-loading, or relay
compatibility problem.

When adopting new MCP spec features:

- keep `tools/list` and `tools/call` behavior standard
- preserve `notifications/tools/list_changed` after direct lazy loading
- map future standard metadata surfaces to the generated manifest before adding
  new bespoke discovery APIs
- keep OAuth and remote exposure concerns scoped to relay/cloud deployments;
  local servers continue to target local controller access
