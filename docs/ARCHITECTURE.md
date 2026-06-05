# Architecture

## Monorepo Structure

```
unifi-mcp/
  apps/
    network/              # UniFi Network MCP server
    protect/              # UniFi Protect MCP server
    access/               # UniFi Access MCP server
    api/                  # REST + GraphQL API server
    worker/               # Cloudflare Worker gateway + npm CLI
  packages/
    unifi-core/           # Shared UniFi controller connectivity
    unifi-mcp-shared/     # Shared MCP server patterns
    unifi-mcp-relay/      # Cloud relay sidecar
  docs/                   # Ecosystem-level docs and plans
  docker/                 # Docker compose for servers and relay
```

The Python workspace is managed by [uv](https://docs.astral.sh/uv/) with `pyproject.toml` at the root defining workspace members. Each Python app and package is independent with its own `pyproject.toml`. `apps/worker/` is excluded from the uv workspace and keeps its own Node/npm dependency graph.

## Package Responsibilities

### unifi-core

Low-level UniFi controller connectivity. No MCP dependency.

| Module | Purpose |
|--------|---------|
| `auth.py` | Authentication (local credentials, API key, dual auth) |
| `connection.py` | Connection manager (aiohttp session, auto-reconnect) |
| `detection.py` | Controller type detection (UniFi OS vs standalone) |
| `retry.py` | Retry logic with exponential backoff |
| `exceptions.py` | Shared exception types |

Used by: `apps/network`, `apps/protect`, `apps/access`, `apps/api`.

### unifi-mcp-shared

Shared MCP server patterns. Depends on `mcp` SDK and `omegaconf`.

| Module | Purpose |
|--------|---------|
| `permissions.py` | Permission checking (category/action, env var overrides) |
| `confirmation.py` | Preview-then-confirm flow for mutations |
| `lazy_tools.py` | Lazy tool loading (on-demand registration) |
| `tool_loader.py` | Tool module import and registration |
| `meta_tools.py` | Meta-tools (tool_index, execute, batch) |
| `config.py` | OmegaConf config loading with env var interpolation |
| `formatting.py` | Response formatting helpers |

Used by: `apps/network`, `apps/protect`, `apps/access`.

### apps/network

The UniFi Network MCP server. 177 tools covering firewall, clients, devices, networks, VPNs, routing, stats, Traffic Flows, and more.

- `src/unifi_network_mcp/` -- server code
  - `main.py` -- entry point, tool registration, transport dispatch
  - `runtime.py` -- singleton factories (`@lru_cache`)
  - `managers/` -- domain logic (one per category)
  - `tools/` -- thin tool wrappers (delegate to managers)
  - `config/config.yaml` -- default configuration
  - `tools_manifest.json` -- pre-generated tool metadata
- `tests/` -- unit and integration tests
- `Makefile` -- app-level development commands
- `Dockerfile` -- container build

### apps/protect

The UniFi Protect MCP server. 58 tools across 8 categories covering cameras, events, Find Anything detection search, recordings, devices (lights/sensors/chimes), liveviews, system status, recognition (faces + license plates), and the Alarm Manager (including AI-powered alarms, which require a SuperAdmin credential). Connects via `uiprotect` (pyunifiprotect) for websocket-based real-time event streaming.

- `src/unifi_protect_mcp/` -- server code
  - `main.py` -- entry point, tool registration, transport dispatch
  - `runtime.py` -- singleton factories (`@lru_cache`)
  - `managers/` -- domain logic (camera, event, recording, light, sensor, chime, liveview, system)
  - `tools/` -- thin tool wrappers (delegate to managers)
  - `resources/` -- MCP resources (event stream, camera snapshots)
  - `config/config.yaml` -- default configuration with Protect-specific event settings
  - `tools_manifest.json` -- pre-generated tool metadata
- `tests/` -- unit and integration tests
- `Makefile` -- app-level development commands
- `Dockerfile` -- container build

### apps/access

The UniFi Access MCP server. 34 tools across 7 categories covering doors, policies, credentials, visitors, events, devices, and system. Uses a **dual-path authentication** model: API key auth on the dedicated Access port (12445) via `py-unifi-access`, and a local proxy session on port 443 for mutations.

- `src/unifi_access_mcp/` -- server code
  - `main.py` -- entry point, tool registration, transport dispatch
  - `runtime.py` -- singleton factories (`@lru_cache`)
  - `managers/` -- domain logic (door, policy, credential, visitor, event, device, system)
  - `tools/` -- thin tool wrappers (delegate to managers)
  - `resources/` -- MCP resources (event stream)
  - `config/config.yaml` -- default configuration with Access-specific event and auth settings
  - `tools_manifest.json` -- pre-generated tool metadata
- `tests/` -- unit and integration tests
- `Makefile` -- app-level development commands
- `Dockerfile` -- container build

**Dual-path auth** is unique to the Access server. The `AccessConnectionManager` maintains two independent sessions: an API key client for read-heavy queries and a proxy session (cookie + CSRF token) for mutations. Each tool declares which auth path it requires.

### packages/unifi-mcp-relay

A standalone sidecar that bridges local MCP servers to a Cloudflare Worker relay gateway, enabling cloud agents to access locally-hosted tools without exposing ports. Communicates with local servers via MCP HTTP transport and with the worker via authenticated WebSocket.

- `src/unifi_mcp_relay/` -- sidecar code
  - `config.py` -- environment variable loading and validation
  - `protocol.py` -- WebSocket message types (register, tool_call, heartbeat, catalog_update)
  - `discovery.py` -- MCP protocol tool discovery from local servers
  - `forwarder.py` -- tool call routing to the correct local server
  - `client.py` -- WebSocket client with reconnection, auth, and timeout enforcement
  - `main.py` -- orchestrator wiring discovery, forwarding, and the client
- `tests/` -- unit and integration tests (mock WebSocket worker)
- `Dockerfile` -- container build

The relay has **no dependency** on the MCP server packages (`unifi-core`, `unifi-mcp-shared`, or any `apps/*`). It is a pure MCP client that discovers tools via the standard MCP protocol.

### apps/worker

The Cloudflare Worker gateway and npm CLI used by cloud agents. The TypeScript Worker receives MCP JSON-RPC over HTTPS, routes tool calls through a Durable Object, and forwards them to connected local relay sidecars over WebSocket. The plain ESM CLI deploys and manages the Worker with Wrangler.

- `bin/cli.mjs` -- npm CLI entry point
- `src/commands/` -- install, upgrade, token rotation, location management, status, and destroy commands
- `src/lib/` -- CLI support code for config, Wrangler, API calls, token generation, and display
- `worker/src/` -- Cloudflare Worker and Durable Object TypeScript code
- `worker/test/` -- Vitest tests for Worker protocol/auth behavior
- `test/cli/` -- Node test runner coverage for CLI utilities
- `package.json` and `package-lock.json` -- npm package for the published CLI
- `worker/package.json` and `worker/package-lock.json` -- isolated Worker build/test dependencies

The Worker intentionally remains a self-contained Node/TypeScript app. It lives in the monorepo so relay protocol changes, MCP metadata changes, and worker contract tests land in the same PR.

## Layering

```
MCP Client (Claude Desktop, LM Studio, automation)
    |
    v  MCP Protocol (stdio / Streamable HTTP / SSE)
    |
FastMCP Server (main.py)
    |
    v  Tool registration (permissioned_tool decorator)
    |
Tool Functions (tools/*.py)           <- thin wrappers
    |
    v  Manager method calls
    |
Manager Layer (managers/*.py)         <- domain logic
    |
    v  unifi-core API calls
    |
Connection Manager (unifi-core)
    |
    v  aiohttp + controller detection
    |
UniFi Controller (REST API)
```

Rules:
- Tool functions must not contain business logic
- Managers must not import from tools (no circular deps)
- All controller communication flows through the connection manager
- All shared objects use `@lru_cache` singleton factories in `runtime.py`

## Adding a New Server

To add a new UniFi application server, follow the pattern established by `apps/protect/` and `apps/access/`:

1. **Create app directory:** `apps/<appname>/`
2. **Create `pyproject.toml`** depending on `unifi-core` and `unifi-mcp-shared`
3. **Add to workspace** in root `pyproject.toml` (`apps/*` is already a glob)
4. **Follow the established pattern** (see `apps/protect/` or `apps/access/` as references):
   - `src/unifi_<appname>_mcp/main.py` -- entry point
   - `src/unifi_<appname>_mcp/managers/` -- domain logic
   - `src/unifi_<appname>_mcp/tools/` -- tool wrappers
   - `src/unifi_<appname>_mcp/resources/` -- MCP resources (if applicable)
   - `src/unifi_<appname>_mcp/config/config.yaml` -- defaults
5. **Reuse shared packages:**
   - `unifi_core` for controller connectivity and auth
   - `unifi_mcp_shared` for permissions, confirmation, lazy loading, config
6. **Add Makefile** targets (test, lint, format, manifest)
7. **Add to root Makefile** delegation targets
8. **Add Dockerfile** following the protect/network/access server pattern

## Shared Patterns

All servers share these patterns via `unifi-mcp-shared`:

- **Permissions:** Category/action model with env var overrides, safe defaults
- **Confirmation:** Preview-then-confirm for all mutations, auto-confirm for automation
- **Lazy tool loading:** Meta-tools registered first, others loaded on demand (~200 vs ~5000 tokens)
- **Config:** OmegaConf YAML with `${oc.env:VAR,default}` interpolation
- **Tool response contract:** `{"success": bool, "data": ...}` or `{"success": false, "error": "..."}`

### MCP Resources (Protect and Access)

Servers may also register MCP resources via a `resources/` directory alongside `tools/`. Resources are ideal for data that benefits from polling rather than explicit tool calls (e.g., event streams, camera snapshots). Resource modules use `@server.resource()` decorators and are imported during startup in `main.py`. Both the Protect server (camera snapshots, event streams) and the Access server (event streams) use this pattern.
