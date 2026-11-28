# unifi-api-server

REST + GraphQL HTTP API for UniFi controllers. Run it as a standalone HTTP
service for desktop apps, web dashboards, Pi extensions, automation services,
and MCP adapters that need typed access to UniFi Network, Protect, Access, InnerSpace, and Drive.

## Quickstart

Two paths — pick the one that matches what you have. Both end with the admin
URL and the bootstrap key printed in your terminal so you can paste and sign
in. **No `UNIFI_API_DB_KEY` to generate, no `.env` file, no `docker exec`
incantations.** The disk-encryption key and the bootstrap admin API key are
both auto-generated on first boot and persisted inside the container's
named volume.

### A. Local clone (developing or testing changes)

Uses [`docker/docker-compose-api.yml`](../../docker/docker-compose-api.yml),
which builds from source and exposes the API on `localhost:8089`.

```bash
./scripts/start-api.sh
```

That's the whole thing. The script builds, starts, waits for first-boot
bootstrap + HTTP readiness, then prints the URL and the key. Paste the key
into <http://localhost:8089/admin/login> and you're in.

### B. Public image (just want to use it)

```bash
docker run -d --name unifi-api-server -p 8080:8080 \
  -v unifi-api-state:/var/lib/unifi-api \
  ghcr.io/sirkirby/unifi-api-server:latest && \
  until docker exec unifi-api-server \
    test -f /var/lib/unifi-api/bootstrap-admin-key 2>/dev/null; \
    do sleep 1; done && \
  echo "" && \
  echo "Admin UI:  http://localhost:8080/admin/login" && \
  echo "Admin key: $(docker exec unifi-api-server cat /var/lib/unifi-api/bootstrap-admin-key)"
```

Paste that whole block into a terminal. It starts the container, waits for
first-boot, and prints the URL and key. Open the URL, paste the key, sign in.

### What's next

Once you're signed in:

- **Register a controller** via the **Controllers** tab (or `POST /v1/controllers`).
- **Optionally add a Site Manager cloud connection** via the **Site Manager**
  tab, to read every console on a UI account from Ubiquiti's cloud. See
  [Site Manager cloud connection](#site-manager-cloud-connection).
- **Mint your own keys** via the **Keys** tab — pick `read`, `write`, or `admin`
  scope per consumer. Once you have a personal key saved, revoke
  `bootstrap-admin` and delete `/var/lib/unifi-api/bootstrap-admin-key`.
- **Explore the APIs:**
  - REST playground: `/v1/docs`
  - GraphQL playground: `/v1/graphql`
  - OpenAPI spec: `/v1/openapi.json`
  - Health: `/v1/health`

Current Network and Protect read surfaces include Network Traffic Flows
(`GET /v1/sites/{site_id}/traffic-flows`, `network.trafficFlows`, with the MCP tool's filters except the client name, e.g.
`?risk=medium&risk=high&destination_region=NL`; each flow carries endpoint regions and matched policies; an unknown parameter is refused) and Protect
Find Anything detection search (`GET /v1/sites/{site_id}/detection-search`,
`protect.searchDetections`).

First GraphQL query:

```bash
curl -s http://localhost:8089/v1/graphql \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ network { clients(controller: \"<id>\") { items { mac hostname } } } }"}'
```

### Production deployments

For shared / production deployments, set `UNIFI_API_DB_KEY` explicitly (e.g.
from a secret manager) so the encryption key lives outside the container
volume:

```bash
docker run -d \
  --name unifi-api-server \
  -p 8080:8080 \
  -e UNIFI_API_DB_KEY=$(openssl rand -hex 32) \
  -v unifi-api-state:/var/lib/unifi-api \
  ghcr.io/sirkirby/unifi-api-server:latest
```

When the env var is set, the file-backed fallback is skipped entirely.

### Reset / lost-key recovery

State (controllers, audit log, admin keys, both encryption and bootstrap key
files) lives in the `unifi-api-state` volume. `docker compose down` keeps it;
`docker compose down -v` wipes for a fresh bootstrap.

If you lose the bootstrap admin key file *and* never saved a personal admin
key, the simplest recovery is to wipe and re-bootstrap:

```bash
docker compose -f docker/docker-compose-api.yml down -v
docker compose -f docker/docker-compose-api.yml up --build -d
```

Note that wiping also drops registered controller credentials, since they
were encrypted with the now-discarded DB key.

## Architecture

`unifi-api-server` is a **standalone HTTP service**. It runs independently of the
MCP servers — both projects share the same manager packages from `unifi-core`,
but neither depends on the other being running. Choose based on the consumer:

- **Hobbyist with Claude Code:** run only the MCP servers; skip `unifi-api-server`.
- **App developer building on the API:** run only `unifi-api-server` via Docker.
- **Tool builder who wants both:** run both as parallel containers (see
  [`docs/docker-compose.example.yml`](docs/docker-compose.example.yml)).

The HTTP layer is FastAPI; GraphQL is Strawberry on top of the same projection
types REST uses, so consumer-facing field names are identical across the two
surfaces. Pagination is cursor-based on REST, slice-based on GraphQL.

The REST action surface is loaded from the packaged
`unifi_api/action_catalog.json`. Product MCP manifests and tool source are
inputs only when that catalog is generated in a repository checkout; at
runtime the API depends on the shared managers and models in `unifi-core`, not
on the Network, Protect, or Access MCP app packages.

### Custom orchestration and MCP adapters

Use the API server as the backend when an application needs dependent calls,
joins, filtering, loops, branching, or an isolated code-execution runtime:

1. Use GraphQL for typed, paginated reads when the application needs field
   selection, or use REST for typed resource reads.
2. Process intermediate results inside the application's own runtime and
   resource limits.
3. Call `POST /v1/actions/{tool_name}` for supported controller operations.
4. Subscribe to the SSE endpoints for live events instead of polling an MCP
   event resource.

An MCP adapter can expose its own tools while using `unifi-api-server` as its
backend. The API and MCP applications share the `unifi-core` manager behavior,
but the adapter defines its outward tool contract. The API server does not
sandbox generated code or set CPU, memory, or execution-time limits for caller
logic. The application must enforce those limits.

Keep mutation approval as two requests. First send the JSON request body with
`"confirm": false` and present the returned preview to the user. After approval,
resend the same body with `"confirm": true`. Do not preview and execute a mutation
inside one code-execution request.

For V2 NAT actions, the generic API preview shows the validated partial
request, without a fresh merged controller document. Confirmation performs
the fresh merge and persistence check in Core. NAT GraphQL remains read-only.

Regenerate all product manifests and the API projection together:

```bash
make manifest
```

Check the committed catalog without rewriting it:

```bash
uv run python scripts/generate_api_action_catalog.py --check
```

Do not edit the catalog directly. Root generation and CI fail when its safety
metadata, manager bindings, exclusions, or bytes drift from the product source.

### Sensitive response fields

REST, GraphQL, and action responses redact known controller secret fields by default. Disable redaction for a trusted local API process with `UNIFI_API_REDACT_SENSITIVE_FIELDS=false` or the global `UNIFI_REDACT_SENSITIVE_FIELDS=false` policy flag when raw values are required. The action endpoint (`POST /v1/actions/{tool}`) rejects `include_sensitive`; response redaction is process policy, not a request argument.

## Site Manager cloud connection

> Site Manager support needs `unifi-api-server` 0.28.0 or later.

The API server serves the same nine read-only reads as the
[Site Manager MCP server](../sitemanager/): hosts, sites, devices, ISP metrics
and SD-WAN configurations for a whole UI account, read from Ubiquiti's cloud
API at `https://api.ui.com`. That destination is fixed and cannot be
configured.

The cloud account is **one account-level connection**, separate from
controllers. It is not a controller record, it takes no host or site, and its
key is never read from the environment, `config.yaml`, or a console's API key.
There is at most one connection per API server.

### Add, rotate, probe and remove

Create the key at [unifi.ui.com](https://unifi.ui.com) under Settings > API
Keys. Every management path needs the `admin` scope. The key is stored
encrypted in the state database with the same column encryption as controller
credentials, and no route, page or command ever returns it: reads show only
`key_configured`. Adding a connection makes no call to the cloud; probe it to
check the key.

**CLI.** The key enters only through a hidden prompt or one line of stdin,
never as an argument:

```bash
unifi-api-server sitemanager add --name "Example account"      # prompts for the key
unifi-api-server sitemanager add --name "Example account" --key-stdin < /path/to/sitemanager-api-key
unifi-api-server sitemanager list                               # metadata only; never the key
unifi-api-server sitemanager probe                              # one small read against api.ui.com
unifi-api-server sitemanager update --rotate-key                # prompts for the replacement key
unifi-api-server sitemanager update --key-stdin < /path/to/new-key
unifi-api-server sitemanager update --name "Renamed account"
unifi-api-server sitemanager delete
```

In the container, run the same commands with `docker exec -i unifi-api-server`
in front, and pass `--config-path` if you use a custom `config.yaml`.

**REST** (`admin` scope):

| Method and path | Purpose |
|---|---|
| `POST /v1/sitemanager/connection` | Create; body `{"name": "...", "site_manager_api_key": "..."}`. Returns `201`, or `409` (`sitemanager_already_configured`) when one exists |
| `GET /v1/sitemanager/connection` | `id`, `name`, `key_configured`, `revision`, `created_at`, `updated_at` |
| `PATCH /v1/sitemanager/connection` | Rename, or rotate with a new `site_manager_api_key` |
| `DELETE /v1/sitemanager/connection` | Remove the connection and its stored key; `204` |
| `POST /v1/sitemanager/connection/probe` | One small read to check the key: `ok`, `latency_ms`, `error_kind`, `checked_at` |

```bash
curl -s -X POST http://localhost:8080/v1/sitemanager/connection \
  -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" \
  --data @- <<< "{\"name\": \"Example account\", \"site_manager_api_key\": \"$(cat /path/to/sitemanager-api-key)\"}"
```

**Admin UI.** The **Site Manager** page at `/admin/sitemanager` adds, edits,
probes and deletes the connection; leave the key field empty when editing to
keep the stored key.

Management responses carry `Cache-Control: no-store`. Each create, update,
delete and probe writes an audit record with the connection id and never the
key; filter them with `GET /v1/audit?sitemanager_connection=<id>`. Updating or
deleting the connection retires the cached cloud session, so later reads use
the new state.

### Reading the account

All read paths need only the `read` scope:

| Surface | Paths |
|---|---|
| REST | `GET /v1/sitemanager/hosts`, `GET /v1/sitemanager/hosts/{host_id}`, `GET /v1/sitemanager/sites`, `GET /v1/sitemanager/devices`, `GET /v1/sitemanager/isp-metrics`, `POST /v1/sitemanager/isp-metrics/query`, `GET /v1/sitemanager/sd-wan-configs`, `GET /v1/sitemanager/sd-wan-configs/{config_id}`, `GET /v1/sitemanager/sd-wan-configs/{config_id}/status` |
| GraphQL | The `sitemanager` namespace: `hosts`, `host`, `sites`, `devices`, `ispMetrics`, `queryIspMetrics`, `sdwanConfigs`, `sdwanConfig`, `sdwanConfigStatus` |
| Actions | `POST /v1/sitemanager/actions/{tool_name}` with `{"args": {...}}`, for the nine `sitemanager_*` read tools |

`POST /v1/sitemanager/isp-metrics/query` is a read that takes its site list in
the body. The paged reads take `page_size` (1-500) and `cursor` and return
`next_cursor`, one page per request. No read takes a `controller`
argument: there is only one account.

```bash
curl -s "http://localhost:8080/v1/sitemanager/hosts?page_size=10" \
  -H "Authorization: Bearer $READ_KEY"

curl -s http://localhost:8080/v1/graphql \
  -H "Authorization: Bearer $READ_KEY" -H "Content-Type: application/json" \
  -d '{"query":"{ sitemanager { hosts(pageSize: 10) { items { id name state } nextCursor } } }"}'

curl -s -X POST http://localhost:8080/v1/sitemanager/actions/sitemanager_list_sites \
  -H "Authorization: Bearer $READ_KEY" -H "Content-Type: application/json" \
  -d '{"args": {"page_size": 10}}'
```

The controller action endpoint `POST /v1/actions/{tool_name}` refuses
`sitemanager_*` tools with `409` and points to the account endpoint, and the
account endpoint refuses console tools the same way. Each account action
writes an audit record.

**What `read` now exposes.** Once a connection exists, every API key with the
`read` scope (and every `admin` key) can read the whole UI account behind it:
every console, site and device the cloud key can see. There is no per-key or
per-console restriction on Site Manager reads.
Before adding a connection, review which keys hold `read`.

Host, site and device ids from these routes belong to the Site Manager family.
Do not pass them to Network, Protect or Access routes.

### Errors

Errors use fixed text and never include the key or upstream exception text.
REST answers `{"detail": {"kind": "...", "message": "..."}}`; GraphQL puts the
code in the error's `extensions`.

| Situation | REST status and `kind` | GraphQL code |
|---|---|---|
| No connection configured (reads) | `503` `sitemanager_not_configured` | `NOT_CONFIGURED` |
| No connection configured (`GET`, `PATCH`, `DELETE` on the connection) | `404` `sitemanager_not_configured` | |
| Stored key cannot be decrypted | `503` `sitemanager_configuration_error` | `NOT_CONFIGURED` |
| Key rejected by Ubiquiti | `502` `sitemanager_auth_failed` | `UPSTREAM_AUTH_FAILED` |
| Ubiquiti refused the request | `502` `sitemanager_permission_denied` | `UPSTREAM_FORBIDDEN` |
| Host or SD-WAN configuration not found | `404` `sitemanager_resource_not_found` | `NOT_FOUND` |
| Rate limited by Ubiquiti | `429` `sitemanager_rate_limited` | `RATE_LIMITED` |
| Network or upstream failure | `502` `sitemanager_upstream_error` | `UPSTREAM_ERROR` |

An unconfigured read answers, for example:

```json
{"detail": {"kind": "sitemanager_not_configured", "message": "Failed to list hosts from Site Manager: Ask an administrator to configure the API cloud connection."}}
```

A probe without a connection answers `503` with `"ok": false` and
`"error_kind": "sitemanager_not_configured"`.

## InnerSpace console product

The API server serves the nine reads and the 15 write actions of the
[InnerSpace MCP server](../innerspace/) for a controller that
declares the `innerspace` product. It reaches the console's InnerSpace
application through a console login session, through the same `unifi-core`
managers as the MCP server. The reads need `unifi-api-server` 0.34.2 or later,
and the write actions 0.34.4 or later.

### Register the controller

`POST /v1/controllers` (or the **Controllers** tab, or the CLI) with
`"innerspace"` in `product_kinds`. InnerSpace needs a **username and password**,
on create and on update: a controller that declares it with only an API token
is refused. The stored API token, if any, is never passed to the InnerSpace
connection, and a console's local API key is never used for InnerSpace. The
account must be able to open the InnerSpace application, for example a Super
Admin.

```bash
curl -s -X POST http://localhost:8080/v1/controllers \
  -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"name": "Example console", "base_url": "https://192.168.1.1",
       "product_kinds": ["innerspace"], "username": "innerspace-mcp",
       "password": "<password>", "verify_tls": false}'
```

The capability probe does not probe InnerSpace, so a controller's
`product_kinds` are what you declare: `GET /v1/controllers/{cid}/capabilities`
lists a declared `innerspace` under `not_probed`, never under `products`.
Whether InnerSpace is installed and running is decided at the first read, from
the console's system endpoint, never from a 403 or a 404. The admin probe
(`POST /v1/controllers/{cid}/probe`) proves only that the login works, not that
InnerSpace is installed, and it spends one console login.

### Reading InnerSpace

All reads need only the `read` scope, name the controller with the `controller`
query parameter, and call the same manager methods:

| Surface | Paths |
|---|---|
| REST | `GET /v1/sites/{site_id}/innerspace/status`, `GET /v1/sites/{site_id}/innerspace/project`, `GET /v1/sites/{site_id}/innerspace/floor-plans`, `GET /v1/sites/{site_id}/innerspace/floor-plans/{plan_id}/walls`, `GET /v1/sites/{site_id}/innerspace/floor-plans/{plan_id}/devices`, `GET /v1/sites/{site_id}/innerspace/floor-plans/{plan_id}/asset`, `GET /v1/sites/{site_id}/innerspace/access-points`, `GET /v1/sites/{site_id}/innerspace/switches`, `GET /v1/sites/{site_id}/innerspace/inventory` |
| GraphQL | The `innerspace` namespace: `status`, `project`, `floorPlans`, `walls`, `placedDevices`, `accessPoints`, `switches`, `inventory`, `planAsset` |
| Actions | `POST /v1/actions/{tool_name}` for the nine `innerspace_*` read tools (writes: see [Writing InnerSpace](#writing-innerspace)) |

The path `site_id` is the controller site of the other console products and is
**ignored** for InnerSpace. The InnerSpace site filter is the query parameter
`innerspace_site_id` (`innerspaceSiteId` in GraphQL), which is the manager's own
`site_id`. Lengths come back in the project's unit, or the `unit` you pass
(`metric` or `imperial`). Walls and placed devices take `limit` (1-2000, default
500) and report `total` and `truncated`. InnerSpace lists are not paged, so
there is no cursor. IDs from these routes belong to the InnerSpace family: do
not pass them to Network, Protect, Access or Site Manager routes.

```bash
curl -s "http://localhost:8080/v1/sites/default/innerspace/floor-plans?controller=<id>" \
  -H "Authorization: Bearer $READ_KEY"

curl -s http://localhost:8080/v1/graphql \
  -H "Authorization: Bearer $READ_KEY" -H "Content-Type: application/json" \
  -d '{"query":"{ innerspace { floorPlans(controller: \"<id>\") { id name scalePerUnit } } }"}'

curl -s -X POST http://localhost:8080/v1/actions/innerspace_list_walls \
  -H "Authorization: Bearer $READ_KEY" -H "Content-Type: application/json" \
  -d '{"controller": "<id>", "args": {"plan_id": "<plan_id>", "limit": 100}}'
```

### Writing InnerSpace

The 15 write tools are catalog actions only: `POST /v1/actions/{tool_name}`
with the `write` scope. There is no REST write route and no GraphQL mutation.

| Category | Actions |
|---|---|
| `walls` | `innerspace_create_walls`, `innerspace_update_walls`, `innerspace_remove_walls` |
| `wall_types` | `innerspace_create_wall_type`, `innerspace_update_wall_type` |
| `attenuation` | `innerspace_create_attenuation_objects`, `innerspace_update_attenuation_objects`, `innerspace_remove_attenuation_objects`, `innerspace_create_attenuation_object_type`, `innerspace_update_attenuation_object_type` |
| `floor_plans` | `innerspace_rename_floor_plan`, `innerspace_set_floor_attenuation`, `innerspace_reorder_floor_plans`, `innerspace_set_plan_scale` |
| `project` | `innerspace_set_project_unit` |

The arguments are the MCP tool's, without `confirm` (see the
[InnerSpace tools](../innerspace/docs/tools.md)); an unknown argument is refused. Field names match the reads (`x1`, `y1`,
`x2`, `y2`, `variant`, `wall_type_id`, ...). Every write that takes lengths
needs `unit`. A batch takes at most 100 creates or updates, or 50 removes.

- `confirm: false` returns a preview of the request only: nothing is read from
  or sent to the console. The MCP tool's preview, which reads the plan and shows
  current values and effects, is not available here.
- `confirm: true` calls the core `apply_*` method: it reads the project fresh,
  refuses a shape that is gone, changed type or moved to another plan since,
  sends one write and reads it back. The
  response is the core result: `success`, `mutation_applied`, `operation`,
  `created_ids`, `effects`, `warnings`, `missing`, and `noop` when nothing was
  sent: `already_applied` (an earlier identical create already landed) or
  `none_found` (none of the ids a remove names is in the project). `success` is `false` whenever the
  write was not applied (`mutation_applied: false`: refused after a send, or not
  sent because the write's time budget ran out first) or its outcome
  is unknown (`mutation_applied: null`; read before retrying). A call that
  changes nothing answers `success: true, mutation_applied: false`.
- A write is refused before anything is sent when InnerSpace is not installed
  or not running on the console.
- One write runs at a time per controller connection of the API server. The
  InnerSpace MCP server, the browser editor and other processes are not locked
  out, which is why a confirm reads again. A field the call does not name keeps
  the value read at the confirm, so an edit made in the InnerSpace app at the
  same moment can be overwritten.
- `UNIFI_READ_ONLY` or `UNIFI_INNERSPACE_READ_ONLY`, and the policy gates
  `UNIFI_POLICY_INNERSPACE_<CATEGORY>_<ACTION>` (and their server-wide and
  global forms), refuse previews and confirmed calls with HTTP `403` and a
  `denied` audit row. Removals and `innerspace_set_plan_scale` are `DELETE`
  actions. See [permissions](../../docs/permissions.md).
- Failures keep the action endpoint's generic contract: HTTP `200`,
  `success: false`, fixed text, the error class audited.

```bash
curl -s -X POST http://localhost:8080/v1/actions/innerspace_create_walls \
  -H "Authorization: Bearer $WRITE_KEY" -H "Content-Type: application/json" \
  -d '{"controller": "<id>", "site": "default", "confirm": true,
       "args": {"plan_id": "<plan_id>", "unit": "metric",
                "walls": [{"x1": 1, "y1": 1, "x2": 3, "y2": 1, "variant": "drywall"}]}}'
```

### Plan images are not served

The API never returns image bytes. `GET .../floor-plans/{plan_id}/asset`,
`planAsset` and `innerspace_get_plan_asset` return image metadata only: file
name, type, pixel size, scale, image scale and offset. Read the image through
the InnerSpace MCP server's plan image resources,
`innerspace://plans/{plan_id}/image` (PNG) and
`innerspace://plans/{plan_id}/image.jpg` (JPEG).

### Errors

Invalid arguments, a missing plan and refused access are answered with fixed
text; the rejected value is never in a response, a log line or an audit record.
REST answers `{"detail": {"kind": "...", "message": "..."}}`; GraphQL puts the
code in the error's `extensions`.

| Situation | REST status and `kind` | GraphQL code |
|---|---|---|
| Invalid arguments (bad id, `limit` out of range) | `422` `invalid_innerspace_request` | `BAD_REQUEST` |
| No such floor plan | `404` `innerspace_not_found` | `NOT_FOUND` |
| The console refused the session for InnerSpace (expired session or no InnerSpace access) | `403` `innerspace_forbidden` | `UPSTREAM_FORBIDDEN` |
| The InnerSpace application answered `503` (restarting or busy) | `503` `innerspace_unavailable`, with `Retry-After` | `UPSTREAM_ERROR` |
| Not installed, not running, login rejected, connection, other HTTP or malformed | `502` `innerspace_upstream_error` | `UPSTREAM_ERROR` |
| The console rate-limited the request | `429` `innerspace_rate_limited` | `RATE_LIMITED` |
| No read slot in time at the operation gate | `503` `controller_busy`, with `Retry-After` | `CONTROLLER_BUSY` |
| Controller does not declare `innerspace` | `409` `capability_mismatch` | |

InnerSpace not being installed is a `502`, never a `404`. Over the action
endpoint, a failure keeps the repository's generic contract: HTTP `200` with
`success: false`, fixed text, and the error class audited as `error_kind`.

### What read and write expose, and redaction

Every key with the `read` scope can read the project's floor plans, wall
positions and device placements for any registered InnerSpace controller, and
every key with the `write` scope can change the layout (walls, wall types,
attenuation objects and their types, plan title, floor attenuation, order and
scale, and the project unit) of any registered InnerSpace controller.
Response redaction hides secret-looking fields by name and is on by default;
MAC addresses, serial numbers and plan geometry are not redacted.

## UniFi Drive console product

The API server serves the eighteen reads and the four preview-first writes of the
[Drive MCP server](../drive/) for a controller that declares the `drive`
product. A UNAS is its own UniFi OS console, so its controller record points
at the NAS, not the gateway. It reads and writes the NAS's UniFi Drive
application through a console login session, through the same `unifi-core`
managers as the MCP server. Run the API from a source checkout
([Quickstart A](#a-local-clone-developing-or-testing-changes)) to use it before
the next API release.

### Register the controller

`POST /v1/controllers` (or the **Controllers** tab, or the CLI) with `"drive"`
in `product_kinds` and the NAS's address as `base_url`. Drive needs a
**username and password** for a local UniFi OS account on the NAS, on create
and on update: a controller that declares it with only an API token is
refused, and the stored API token, if any, is never passed to the Drive
connection. A UI.com account with MFA cannot log in. Reads need an account
with access to UniFi Drive; writes need an administrator of UniFi Drive.

```bash
curl -s -X POST http://localhost:8080/v1/controllers \
  -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"name": "Example NAS", "base_url": "https://192.168.1.20",
       "product_kinds": ["drive"], "username": "drive-api",
       "password": "<password>", "verify_tls": false}'
```

The capability probe does not probe Drive: `GET /v1/controllers/{cid}/capabilities`
lists a declared `drive` under `not_probed`, never under `products`. The Drive
connection logs in on its first request, not when it is built, and after a
rejected login it pauses further logins on an escalating cool-down. The admin
probe (`POST /v1/controllers/{cid}/probe`) logs in and reads the console's
system endpoint once: it proves the login works, not that UniFi Drive is
installed.

### Reading Drive

All reads need only the `read` scope, name the controller with the `controller`
query parameter, and call the same manager methods:

| Surface | Paths |
|---|---|
| REST | Under `/v1/sites/{site_id}/drive/`, in the table below |
| GraphQL | The `drive` namespace, in the table below |
| Actions | `POST /v1/actions/{tool_name}` for the eighteen `drive_*` read tools |

| Reads | REST `GET` | GraphQL field | Action |
|---|---|---|---|
| NAS console | `/v1/sites/{site_id}/drive/system` | `systemInfo` | `drive_get_system_info` |
| System log, one page | `/v1/sites/{site_id}/drive/logs` | `logs` | `drive_list_logs` |
| Storage pools | `/v1/sites/{site_id}/drive/storage-pools` | `storagePools` | `drive_list_storage_pools` |
| What each pool's used space is used by | `/v1/sites/{site_id}/drive/storage-usage` | `storageUsage` | `drive_get_storage_usage` |
| Disks | `/v1/sites/{site_id}/drive/disks` | `disks` | `drive_list_disks` |
| Network throughput now | `/v1/sites/{site_id}/drive/network-throughput` | `networkThroughput` | `drive_get_network_throughput` |
| Fan profile | `/v1/sites/{site_id}/drive/fan-profile` | `fanProfile` | `drive_get_fan_profile` |
| Per-disk activity over a window | `/v1/sites/{site_id}/drive/disk-stats` | `diskStats` | `drive_get_disk_stats` |
| Shared drives | `/v1/sites/{site_id}/drive/shared-drives` | `sharedDrives` | `drive_list_shared_drives` |
| One shared drive, by id | `/v1/sites/{site_id}/drive/shared-drives/{drive_id}` | `sharedDrive` | `drive_get_shared_drive` |
| Every drive's snapshot settings and state | `/v1/sites/{site_id}/drive/snapshot-overview` | `snapshotOverview` | `drive_get_snapshot_overview` |
| One shared drive's snapshots, by name | `/v1/sites/{site_id}/drive/snapshots/shared/{shared_drive_name}` | `snapshots` | `drive_list_snapshots` |
| SMB, NFS and Time Machine | `/v1/sites/{site_id}/drive/file-services` | `fileServices` | `drive_get_file_services` |
| SMB Trash for personal drives | `/v1/sites/{site_id}/drive/smb-advanced-settings` | `smbAdvancedSettings` | `drive_get_smb_advanced_settings` |
| rsync service | `/v1/sites/{site_id}/drive/rsync-settings` | `rsyncSettings` | `drive_get_rsync_settings` |
| NFS clients | `/v1/sites/{site_id}/drive/nfs-connections` | `nfsConnections` | `drive_list_nfs_connections` |
| Users | `/v1/sites/{site_id}/drive/users` | `users` | `drive_list_users` |
| User groups | `/v1/sites/{site_id}/drive/groups` | `groups` | `drive_list_groups` |

The path `site_id` is the controller site of the other console products and is
**ignored** for Drive: a NAS has no sites. Byte counts are `BigInt` in GraphQL.
IDs from these routes belong to the Drive family: do not pass them to other
products' routes. The arguments are the MCP tools' arguments:

- `disks` takes `include_empty` (default false) and `include_cache` (default
  true).
- The system log is the one paged read: each call answers one page, newest
  first, as `{"entries": [...], "next_cursor": ...}`. Pass `next_cursor` back as
  `cursor`, with the same filters, for the next page; it is null on the last.
  The filters are `limit` (1 to 500, default 50), `severities`, `category`,
  `types`, `keyword`, `scope` (`all`, `audit` or `flow`), and `after` and
  `before` (ISO 8601 with an offset). Over REST, repeat `severities` and `types`
  for more than one value. An unknown category or type is a `422`.
- Disk stats take `hours` (1 to 2160, default 24). The REST route and the action
  leave out each disk's per-bucket `samples` unless `include_samples` is true:
  they add about 12 KB per disk per day at 15-minute buckets. GraphQL returns
  them only when a query selects `samples`.
- A shared drive's snapshots are addressed by the shared drive's **name**, as
  Drive addresses them, not by its id: take it from the shared drive list or
  from `shared_drive_name` in the snapshot overview.
- The other lists are whole, with no cursor.

```bash
curl -s "http://localhost:8080/v1/sites/default/drive/storage-pools?controller=<id>" \
  -H "Authorization: Bearer $READ_KEY"

curl -s http://localhost:8080/v1/graphql \
  -H "Authorization: Bearer $READ_KEY" -H "Content-Type: application/json" \
  -d '{"query":"{ drive { nfsConnections(controller: \"<id>\") { client sharedDrives { name permission exportPath } } } }"}'
```

### Changing file services and NFS clients

The four writes are catalog actions and need the `write` scope:
`drive_set_file_service` (SMB, NFS or Time Machine on or off),
`drive_add_nfs_connection`, `drive_update_nfs_connection` and
`drive_remove_nfs_connection`. Their arguments are the MCP tools' arguments.

What a toggle does beyond the service you name, which the request-only preview
does not show:

- **Turning SMB off also turns Time Machine off**, because Time Machine runs over
  SMB, and turning SMB back on leaves Time Machine off: turn it on again with
  `drive_set_file_service` (`time_machine`, `true`). Turning Time Machine on
  while SMB is off is refused.
- Turning any service off disconnects its clients.
- Turning NFS off keeps the NFS client list, so those clients can mount again
  when NFS is turned back on.

- `confirm: false` (the default) validates the request and returns a request-only
  preview with `requires_confirmation: true`. It calls no manager and sends
  nothing to the NAS, so it does not show the NAS's current state or the
  warnings the MCP server's preview adds; use the MCP tool for those.
- `confirm: true` plans the change from fresh NAS state and applies it in one
  manager call, then reads it back. The result is the MCP tool's data:
  `{"service", "enabled", "changed"}` for a toggle, `{"connection": ...}` for an
  added or updated client, `{"removed": "<client>"}` for a removal. A toggle that
  changes nothing sends nothing and answers `changed: false`.
- A write stopped before its change was sent answers `success: false` with
  `mutation_applied: false`: nothing changed. A change that was sent and never
  answered answers `success: false` with `mutation_applied: null`: it may be
  live, so read it back before retrying. Neither is ever a success.

```bash
curl -s -X POST http://localhost:8080/v1/actions/drive_add_nfs_connection \
  -H "Authorization: Bearer $WRITE_KEY" -H "Content-Type: application/json" \
  -d '{"controller": "<id>", "site": "default", "confirm": true,
       "args": {"client": "192.168.1.50", "shared_drives": [{"id": "<shared drive id>", "permission": "ro"}]}}'
```

Drive keeps every NFS client in one list and replaces it as a whole. A
confirmed NFS write reads the list again just before it writes and stops if it
changed. The API's operation gate runs confirmed writes for one NAS one at a
time, but only within this API process: the Drive MCP server is a separate
process, and a write from it that lands between the API's last read and its
write is overwritten without either reporting it.

`UNIFI_DRIVE_READ_ONLY=true` (or `UNIFI_READ_ONLY=true`) refuses every Drive
write on this API, previews included, with `403`. The Drive MCP server's
per-category `UNIFI_POLICY_DRIVE_*` gates are **not** applied by the API.

### Errors

Read errors are answered with fixed text built from the request path, the HTTP
status and Drive's own capped message, never the NAS address; invalid arguments
and a missing shared drive never echo the rejected value. The text of a `403`,
`429` or `502` names the request path, which for the system log includes the
filters and cursor sent. REST answers
`{"detail": {"kind": "...", "message": "..."}}`; GraphQL puts the code in the
error's `extensions`.

| Situation | REST status and `kind` | GraphQL code |
|---|---|---|
| Invalid arguments | `422` `invalid_drive_request` | `BAD_REQUEST` |
| No such shared drive (by id, or by name for snapshots) | `404` `drive_not_found` | `NOT_FOUND` |
| The NAS refused the account (no access to UniFi Drive) | `403` `drive_forbidden` | `UPSTREAM_FORBIDDEN` |
| Login rejected, connection, Drive not installed, other HTTP or malformed | `502` `drive_upstream_error` | `UPSTREAM_ERROR` |
| The NAS rate-limited the request | `429` `drive_rate_limited` | `RATE_LIMITED` |
| No read slot in time at the operation gate | `503` `controller_busy`, with `Retry-After` | `CONTROLLER_BUSY` |
| Controller does not declare `drive` | `409` `capability_mismatch` | |

Over the action endpoint, a failure keeps the repository's generic contract:
HTTP `200` with `success: false`, fixed text, and the error class audited as
`error_kind`, plus `mutation_applied` for the two write outcomes above.

### What read exposes, and redaction

Every key with the `read` scope can read the NAS's storage layout, disk serial
numbers, shared drive names, NFS client addresses, users (usernames, names,
email addresses, roles and last login) and the system log, whose messages name
users, client addresses, drives and pools, for any registered Drive controller.
The rsync account's password is never returned. Response redaction hides
secret-looking fields by name and is on by default; MAC addresses, serial
numbers, client addresses, email addresses and log messages are not redacted.

## Distribution

`unifi-api-server` is published to:

- **PyPI:** `pip install unifi-api-server`
- **GHCR:** `docker pull ghcr.io/sirkirby/unifi-api-server:latest`
- **GitHub Releases:** wheels attached to each `api/v*` tag

The distribution name `unifi-api-server` establishes `unifi-api-*` as the family
namespace for the API and its future ecosystem (planned: `unifi-api-python-sdk`,
`unifi-api-ts-sdk`, `unifi-api-cli`). The import name remains `unifi_api`.

## Configuration

Two layers — environment variables override `config.yaml`. Defaults work for a
standard local install; override only what you need.

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_API_DB_KEY` | _auto-generated on first boot_ | Encrypts controller credentials at rest. Auto-generated and persisted to `<state_dir>/.db_encryption_key` if unset. **Not a login credential** — set explicitly in production via secret manager so the key lives outside the volume. |
| `UNIFI_API_STATE_DIR` | `/var/lib/unifi-api` | Where the SQLite state DB lives |
| `UNIFI_API_HTTP_HOST` | `127.0.0.1` | Bind address (set to `0.0.0.0` for non-localhost access) |
| `UNIFI_API_HTTP_PORT` | `8080` | Listen port |
| `UNIFI_API_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `UNIFI_API_GATE_WRITE_HOLD_SECONDS` | `120` | How long one write to a controller application may hold its turn (10 to 3600) before requests queued behind it are refused as busy |
| `UNIFI_API_GATE_CALL_WAIT_SECONDS` | `25` | How long a request waits for its turn before it is refused as busy (1 to 3600) |
| `UNIFI_API_GATE_READ_CONCURRENCY` | `8` | Reads per controller application that may run at once (1 to 64) |

### Controller operation gate

Writes to one controller application (a stored controller's Network, Protect
or Access) run one at a time, in the order they arrive: a confirmed action
holds the write turn for the manager call, so two clients never interleave a
read-modify-write. Reads (read actions, resource routes, GraphQL) share a
capped number of slots per controller application and never wait behind
writes; event streams take none. A REST request that cannot get its turn in
time gets `503` with `Retry-After`, nothing is sent to the controller, and an
audit row records it. A GraphQL field that cannot gets HTTP `200` with an error
whose `extensions.code` is `CONTROLLER_BUSY` and `extensions.retryAfter` the
suggested delay; GraphQL busy errors write no audit row. A confirmed action cut
off at the hold budget answers `success: false` with `mutation_applied: null`,
since it may have reached the controller (read the resource back before
retrying), or `false` when it was refused before sending. A REST read that goes
through `ConnectionManager.request()` and whose controller application answers
`503` (restarting or busy) gets `503` with `Retry-After` and `detail.kind`
`controller_unavailable`, no audit row, and no controller text; collection
refreshes and GraphQL error mapping are unchanged. A request holds at most
one read slot per controller application, released when it ends, and a
multi-controller query waits for each in turn, at most the wait budget each.
Controller reads outside the cap: the capability probes
(`/v1/controllers/{id}/capabilities`) and controller probes, which manage the
connection itself. A value out of range stops the server at startup. The
guarantee is per API server process; these variables apply to the API server
only, not to the MCP servers, which have their own
(`UNIFI_<SERVER>_WRITE_HOLD_SECONDS` and so on).

Per-controller credentials are stored encrypted in the state DB after the first
`POST /v1/controllers` call — no controller credentials in env vars. The
optional Site Manager cloud key is stored the same way and is never read from
the environment; see [Site Manager cloud connection](#site-manager-cloud-connection).

## MFA / 2FA support

`unifi-api-server` connects to UniFi controllers using local-account credentials
(username + password + optional API token). It does **not** currently support
controllers that require MFA / 2FA on local accounts.

If your controller has MFA enabled, you'll need either:
- A separate local account with MFA disabled (recommended for service accounts)
- A long-lived API token (UniFi Network and Protect both support this on recent
  firmware)

This is the same constraint the MCP servers (`unifi-network-mcp`,
`unifi-protect-mcp`, `unifi-access-mcp`) inherit. See issue #150 for context.

## Documentation

- [MAC parameter migration](../network/docs/mac-parameter-migration.md) for Network MCP and API action calls.

- **Reference docs** are auto-generated and drift-gated. Browse them in-repo or
  via the live exploration UIs:
  - [REST OpenAPI spec (JSON)](openapi.json)
  - [REST reference (markdown)](docs/openapi-reference.md)
  - [GraphQL SDL](src/unifi_api/graphql/schema.graphql)
  - [GraphQL reference (markdown)](docs/graphql-reference.md)
  - **Live exploration:** Swagger UI at `/v1/docs`, GraphiQL at `/v1/graphql`
- [`docs/README.md`](docs/README.md) — index linking all artifacts plus
  deployment patterns
- [`docs/graphql-versioning.md`](docs/graphql-versioning.md) — schema
  versioning policy

## Development

The project uses an `uv` workspace covering `apps/api/` plus the shared
`packages/unifi-core/` and the six MCP apps. Common development commands:

```bash
# Install everything once
uv sync --all-packages

# Run the unifi-api-server test suite (~700 tests)
uv run --package unifi-api-server pytest apps/api/tests

# Run live smoke against real controllers (requires .env)
uv run --package unifi-api-server python scripts/live_api_smoke.py --output /tmp/smoke.json

# Re-export drift-gated artifacts after schema changes
uv run --package unifi-api-server python -m unifi_api.graphql.docgen
```

The full project quality gate runs `make pre-commit` (lint + format + sync-skills
+ tests) at the repo root.

### Image-level smoke harness

`scripts/live_api_smoke.py` boots the API in-process via `ASGITransport`,
which means it cannot detect dep-closure bugs that only manifest in the
published Docker image (e.g. a missing runtime dependency that gets
masked by a `uv sync --all-packages` workspace). For that, use
`scripts/smoke-api-image.sh`:

```bash
# Optionally point at a real controller so authenticated paths get tested.
# Without these env vars the sweep still verifies first-boot, auth, and
# the capability_mismatch / api_key_required error paths.
export UNIFI_HOST=10.0.0.1
export UNIFI_USERNAME=svc
export UNIFI_PASSWORD=...
export UNIFI_API_TOKEN=...   # optional; required for DPI to return 200

./scripts/smoke-api-image.sh
```

The script wipes any existing state, rebuilds the image, brings it up,
registers a controller (when env vars are set), runs
`scripts/api_image_smoke.py` against every GET endpoint in the schema,
and fails on any 5xx or network error. Tears down on exit.

This is the harness that should run on every release tag.

## License

See the repository root [LICENSE](../../LICENSE) file. MIT License, © 2025 Chris Kirby.
