# Architecture

## Monorepo Structure

```
unifi-mcp/
  apps/
    network/              # UniFi Network MCP server
    protect/              # UniFi Protect MCP server
    access/               # UniFi Access MCP server
    sitemanager/          # UniFi Site Manager MCP server (Ubiquiti cloud, read-only)
    innerspace/           # UniFi InnerSpace MCP server (console login, read-only; not yet released)
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
| `operation_gate.py` | Per-controller operation gate: one write at a time in arrival order, a capped number of reads |
| `exceptions.py` | Shared exception types |
| `incident_evidence.py` | Versioned cross-product incident evidence contract ([details](incident-evidence.md)); Network and Protect normalizers live in `network/` and `protect/` |
| `source_page.py` | One bounded manager read with its totals, continuation state and submitted bounds |
| `event_timeline.py` | Legacy timeline shape, with a projection from evidence records |
| `sitemanager/` | Site Manager cloud client, managers and models; the fixed `https://api.ui.com` origin lives in `sitemanager/managers/connection_manager.py` |
| `innerspace/` | InnerSpace client, managers and models; reads under `/proxy/innerspace/` with the console session only, lengths in the project unit; the session client is `innerspace/managers/connection_manager.py` |

Used by: `apps/network`, `apps/protect`, `apps/access`, `apps/sitemanager`, `apps/innerspace`, `apps/api`.

### unifi-mcp-shared

Shared MCP server patterns. Depends on MCP SDK 2.x and `omegaconf`. The shared
server negotiates the current Discover-era and legacy Initialize-era protocols
per connection, so one process can serve clients at either migration state.

| Module | Purpose |
|--------|---------|
| `permissions.py` | Permission checking (category/action, env var overrides) |
| `confirmation.py` | Preview-then-confirm flow for mutations |
| `lazy_tools.py` | Lazy tool loading (on-demand registration) |
| `tool_loader.py` | Tool module import and registration |
| `meta_tools.py` | Meta-tools (tool_index, execute, batch, batch_status, batch_cancel) |
| `tool_gate.py` | Runs each domain tool call through its controller's operation gate |
| `config.py` | OmegaConf config loading with env var interpolation |
| `formatting.py` | Response formatting helpers |

Used by: `apps/network`, `apps/protect`, `apps/access`, `apps/sitemanager`, `apps/innerspace`.

### apps/network

The UniFi Network MCP server. 217 tools covering firewall, clients, devices, networks, VPNs, routing, stats, Traffic Flows, and more.

- `src/unifi_network_mcp/` -- server code
  - `main.py` -- entry point, tool registration, transport dispatch
  - `runtime.py` -- singleton factories (`@lru_cache`)
  - domain logic lives in `packages/unifi-core/src/unifi_core/network/managers/`
  - `tools/` -- thin tool wrappers (delegate to managers)
  - `config/config.yaml` -- default configuration
  - `tools_manifest.json` -- pre-generated tool metadata
- `tests/` -- unit and integration tests
- `Makefile` -- app-level development commands
- `Dockerfile` -- container build

### apps/protect

The UniFi Protect MCP server. 68 tools across 9 categories covering cameras (including crossing line and smart-detect zone names), events, Find Anything detection search, recordings, devices (lights/sensors/chimes), liveviews, system status, recognition (faces + license plates), and the Alarm Manager (including AI-powered alarms, which require a SuperAdmin credential). Connects via `uiprotect` (pyunifiprotect) for websocket-based real-time event streaming.

- `src/unifi_protect_mcp/` -- server code
  - `main.py` -- entry point, tool registration, transport dispatch
  - `runtime.py` -- singleton factories (`@lru_cache`)
  - domain logic lives in `packages/unifi-core/src/unifi_core/protect/managers/` (camera, event, recording, light, sensor, chime, liveview, alarm, system)
  - `tools/` -- thin tool wrappers (delegate to managers)
  - `resources/` -- MCP resources (event stream, camera snapshots)
  - `config/config.yaml` -- default configuration with Protect-specific event settings
  - `tools_manifest.json` -- pre-generated tool metadata
- `tests/` -- unit and integration tests
- `Makefile` -- app-level development commands
- `Dockerfile` -- container build

### apps/access

The UniFi Access MCP server. 38 tools across 7 categories covering doors, policies, credentials, visitors, events, devices, and system. Uses a **dual-path authentication** model: API key auth on the dedicated Access port (12445) via `py-unifi-access`, and a local proxy session on port 443 for mutations.

- `src/unifi_access_mcp/` -- server code
  - `main.py` -- entry point, tool registration, transport dispatch
  - `runtime.py` -- singleton factories (`@lru_cache`)
  - domain logic lives in `packages/unifi-core/src/unifi_core/access/managers/` (door, policy, credential, visitor, event, device, system)
  - `tools/` -- thin tool wrappers (delegate to managers)
  - `resources/` -- MCP resources (event stream)
  - `config/config.yaml` -- default configuration with Access-specific event and auth settings
  - `tools_manifest.json` -- pre-generated tool metadata
- `tests/` -- unit and integration tests
- `Makefile` -- app-level development commands
- `Dockerfile` -- container build

**Dual-path auth** is unique to the Access server. The `AccessConnectionManager` maintains two independent sessions: an API key client for read-heavy queries and a proxy session (cookie + CSRF token) for mutations. Each tool declares which auth path it requires.

### apps/sitemanager

The UniFi Site Manager MCP server. 9 read-only domain tools over Ubiquiti's cloud Site Manager API: hosts, sites, devices, ISP metrics, and SD-WAN configurations, plus the six shared meta-tools. It has no writes, no policy gates, no events or MCP resources, and no support-bundle tool.

- `src/unifi_sitemanager_mcp/` -- server code
  - `tools/` -- tool wrappers; the managers live in `unifi_core.sitemanager`
  - `config/config.yaml` -- runtime settings only; no credential
- `tests/` -- unit tests; they pass a loopback `base_url` and never reach the cloud
- `Dockerfile` -- container build

Unlike the console servers, it has no controller: every request goes to the fixed origin `https://api.ui.com`, which no setting can change. Its one credential, a Site Manager API key, is read only from `UNIFI_SITEMANAGER_API_KEY` or its `_FILE` / `_COMMAND` form, with no fallback to `UNIFI_API_KEY`, shared `UNIFI_*` variables, `config.yaml` or `CONFIG_PATH`. The key reads every console on the account. Its host, site and device IDs belong to their own tool family. It makes no request at startup, and without a key it registers only `sitemanager_setup_status`. HTTP is opt-in on port 3003, and the Cloud Relay does not reach it unless an operator adds it.

### apps/innerspace

The UniFi InnerSpace MCP server, not yet released. 9 read-only domain tools over the InnerSpace application on a UniFi OS console: its status, the project, floor plans, walls, placed devices, access points, switches, unplaced inventory and a plan's image metadata, plus the six shared meta-tools. It has no writes, no policy gates in this version, no events, and no support-bundle tool. It registers two MCP resource templates for a plan's image, `innerspace://plans/{plan_id}/image` (PNG) and `innerspace://plans/{plan_id}/image.jpg` (JPEG).

- `src/unifi_innerspace_mcp/` -- server code
  - `main.py` -- entry point, tool registration, transport dispatch
  - `runtime.py` -- singleton factories for the managers
  - domain logic lives in `packages/unifi-core/src/unifi_core/innerspace/managers/`, released in `unifi-core` before the app
  - `tools/` -- tool wrappers in four category modules (`status`, `project`, `floor_plans`, `devices`); the managers live in `unifi_core.innerspace`
  - `arguments.py` -- shared argument types, kept outside `tools/` so importing them registers no tool
  - `resources/` -- the plan image resources (one per image type) and their URI templates
  - `config/config.yaml` -- console connection and runtime settings; no `api_key`
- `tests/` -- unit tests with a fake or loopback console; they never contact a real one
- `Dockerfile` -- container build

It reads through a console login session (`unifi_core.innerspace.managers.connection_manager`), never an API key, and never reads `UNIFI_API_KEY`. The session client does not follow redirects or use proxy environment variables, and builds its error text from fixed strings. Positions come back in the project's unit, in the plan's own frame; each plan carries its scale, image scale and offset so a position can be placed on the image. Its IDs belong to their own tool family. It connects in the background after answering the client, and whether InnerSpace is installed and running is decided at the first read from the console's system endpoint, not probed at startup. Without a host it registers only `innerspace_setup_status`. HTTP is opt-in on port 3005, and the Cloud Relay does not reach it unless an operator adds it. The read-only guarantee covers the nine domain tools; the meta-tools are not counted as read-only tools.

### apps/api

The independent `unifi-api-server` HTTP service for custom applications,
automation, and adapters. It provides typed REST resources, read-only GraphQL
queries, a REST action endpoint for supported controller operations, SSE
streams, scoped API keys, encrypted controller credentials, audit records, and
an administrative control plane. An MCP adapter can expose tools to its clients
while using the API server as its backend.

The API app and the MCP apps independently consume the manager layer from `unifi-core`; the API does not proxy or require the MCP servers. It is also not part of the Cloud Relay request path.

The API also serves the nine Site Manager reads. The cloud account is one account-level connection, separate from controller records: an administrator adds it, its key is stored encrypted in the API database, and a separate factory builds the Site Manager managers from it. It never reads the MCP server's environment or imports the MCP app. See [Site Manager cloud connection](../apps/api/README.md#site-manager-cloud-connection).

It serves the nine InnerSpace reads for a controller that declares the `innerspace` product, through the same `unifi-core` managers: REST routes, a GraphQL `innerspace` namespace and catalog actions share one error mapping with fixed text. A stored controller needs a username and password for InnerSpace, and its API token is never passed to the InnerSpace connection. No API surface returns plan image bytes. See [InnerSpace console product](../apps/api/README.md#innerspace-console-product).

### packages/unifi-mcp-relay

A standalone Relay sidecar that acts as a pure MCP HTTP client and forwarder. It discovers configured local MCP servers over HTTP and maintains an outbound authenticated WebSocket to the Worker gateway, enabling remote MCP access without exposing inbound local ports.

- `src/unifi_mcp_relay/` -- sidecar code
  - `config.py` -- environment variable loading and validation
  - `protocol.py` -- WebSocket message types (register, tool_call, heartbeat, catalog_update)
  - `discovery.py` -- MCP protocol tool discovery from local servers
  - `forwarder.py` -- tool call routing to the correct local server
  - `client.py` -- WebSocket client with reconnection, auth, and timeout enforcement
  - `main.py` -- orchestrator wiring discovery, forwarding, and the client
- `tests/` -- unit and integration tests (mock WebSocket worker)
- `Dockerfile` -- container build

The Relay does not import or depend on the individual MCP server app packages (`apps/network`, `apps/protect`, `apps/access`, `apps/sitemanager`, or `apps/innerspace`). It uses shared MCP protocol and metadata utilities from `unifi-mcp-shared`, and declares a `unifi-core` floor for controller credential redaction without importing it. It forwards every tool call, including the incident evidence tools; the worker provides `unifi_location_timeline`. The Relay-to-local-server leg is MCP over HTTP. The API server is not involved.

### apps/worker

The Cloudflare Worker gateway is the authenticated edge MCP endpoint and broker used by remote MCP clients. The TypeScript Worker receives MCP JSON-RPC over HTTPS, routes tool calls through a Durable Object, and forwards them to connected local Relay sidecars over WebSocket. The plain ESM CLI deploys and manages the Worker with Wrangler.

- `bin/cli.mjs` -- npm CLI entry point
- `src/commands/` -- install, upgrade, token rotation, location management, status, and destroy commands
- `src/lib/` -- CLI support code for config, Wrangler, API calls, token generation, and display
- `worker/src/` -- Cloudflare Worker and Durable Object TypeScript code
- `worker/test/` -- Vitest tests for Worker protocol/auth behavior
- `test/cli/` -- Node test runner coverage for CLI utilities
- `package.json` and `package-lock.json` -- npm package for the published CLI
- `worker/package.json` and `worker/package-lock.json` -- isolated Worker build/test dependencies

The Worker intentionally remains a self-contained Node/TypeScript app. It lives in the monorepo so relay protocol changes, MCP metadata changes, and worker contract tests land in the same PR.

The complete Cloud Relay request path is:

```text
Remote MCP client → Worker gateway → outbound WebSocket → Relay sidecar → local MCP servers over HTTP
```

`unifi-api-server` is not in this path.

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
Manager Layer (unifi_core/<product>/managers/*.py)  <- domain logic
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

To add a new UniFi application server, follow the pattern established by `apps/protect/` and `apps/access/` for a console product, `apps/sitemanager/` for a cloud API, or `apps/innerspace/` for a console application read through a login session with no API key:

1. **Create app directory:** `apps/<appname>/`
2. **Create `pyproject.toml`** depending on `unifi-core` and `unifi-mcp-shared`
3. **Add to workspace** in root `pyproject.toml` (`apps/*` is already a glob)
4. **Follow the established pattern** (see `apps/protect/` or `apps/access/` as references):
   - `src/unifi_<appname>_mcp/main.py` -- entry point
   - `src/unifi_<appname>_mcp/runtime.py` -- singleton factories for the managers
   - domain logic in `packages/unifi-core/src/unifi_core/<appname>/managers/`, released in `unifi-core` before the app that uses it
   - `src/unifi_<appname>_mcp/tools/` -- tool wrappers
   - `src/unifi_<appname>_mcp/resources/` -- MCP resources (if applicable)
   - `src/unifi_<appname>_mcp/config/config.yaml` -- defaults
5. **Reuse shared packages:**
   - `unifi_core` for controller connectivity and auth
   - `unifi_mcp_shared` for permissions, confirmation, lazy loading, config
   - pass `gate_provider` (`None` only for a server with no controller) and the connection wait as `connection_decorator`, so tool calls go through the operation gate
6. **Add Makefile** targets (test, lint, format, manifest)
7. **Add to root Makefile** delegation targets
8. **Add Dockerfile** following the protect/network/access server pattern
9. **Register the app with the repo's release and check tooling.** Each of these enumerates the servers and is enforced by a test or CI:
   - Workflows `test-<appname>.yml`, `release-<appname>.yml`, `docker-<appname>.yml` (pass `CORE_VERSION`/`SHARED_VERSION` when the Dockerfile declares them)
   - `scripts/generate_server_manifest.py` (`APP_CONFIGS`), `scripts/smoke_mcp_metadata.py` (`SERVER_SPECS`, `OFFLINE_SERVER_NAMES`), `scripts/check_pin_alignment.py` (`SECURITY_FLOORS`, `DOWNSTREAM_PACKAGES`, `FLOOR_ONLY_CORE_EXTRAS`), `scripts/generate_release_notes.py` (`APP_CONFIGS`, `PRODUCT_KEYS`, the tag regex)
   - The icon family and tool prefix in `unifi_mcp_shared/metadata.py`: an unknown icon family fails at startup
   - Root tests that list servers: `tests/test_server_manifest.py`, `tests/test_smoke_mcp_metadata.py`, `tests/test_package_versions.py`, `tests/test_manifest_permission_coverage.py`, `tests/test_app_tool_index_lookup.py`, `tests/test_http_deployment_defaults.py`
   - `.github/dependabot.yml` Docker directories, `.myco/myco.yaml` release tags, `uv.lock`
10. **Use one lowercase token for the app name** (as in `sitemanager`). Scripts derive the directory, Python module, env prefix and plugin name from it, and a hyphen or underscore breaks several of them.
11. **Commit a placeholder `tools_manifest.json` before the first `make manifest`:** the wheel force-includes it, so the package cannot be installed to generate it otherwise.

`apps/sitemanager/` is the reference for a server with no controller: an API key as its only credential, no startup connection, and no support bundle. `apps/innerspace/` is the reference for a read-only console application that uses the console login session only: category modules with `Annotated` argument types outside `tools/`, a background connection, and setup mode without a host.

## Shared Patterns

All servers share these patterns via `unifi-mcp-shared`:

- **Permissions:** Category/action model with env var overrides, safe defaults
- **Confirmation:** Preview-then-confirm for all mutations, auto-confirm for automation
- **Operation gate:** Confirmed writes to one controller application run one at a time in arrival order, from direct calls and batches alike; reads are capped. The guarantee is per server process
- **Lazy tool loading:** Meta-tools registered first, others loaded on demand (~200 vs ~5000 tokens)
- **Config:** OmegaConf YAML with `${oc.env:VAR,default}` interpolation
- **Tool response contract:** `{"success": bool, "data": ...}` or `{"success": false, "error": "..."}`

### MCP Resources (Protect, Access and InnerSpace)

Servers may also register MCP resources via a `resources/` directory alongside `tools/`. Resources are ideal for data that benefits from polling rather than explicit tool calls (e.g., event streams, camera snapshots). Resource modules use `@server.resource()` decorators and are imported during startup in `main.py`. The Protect server (camera snapshots, event streams), the Access server (event streams) and the InnerSpace server (floor plan images, read on demand) use this pattern.
