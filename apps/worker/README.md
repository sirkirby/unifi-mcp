# UniFi MCP Relay Worker

A Cloudflare Worker that enables cloud agents to access locally-hosted UniFi MCP servers via a secure relay gateway.

---

## How It Works

Cloud agents communicate with your local UniFi MCP server through a two-leg relay:

```
Cloud Agent (Claude, n8n, etc.)
        |  HTTPS POST /mcp  (Bearer AGENT_TOKEN)
        v
Cloudflare Worker  ──────────────────────────────────  Durable Object (RelayObject)
                                                                |
                                              WebSocket (WSS) /ws  (relay_token)
                                                                |
                                                   Relay sidecar (local network)
                                                                |
                                                MCP over HTTP to local servers
```

The Relay sidecar connects to each configured local MCP server using MCP over HTTP only.

The Durable Object persists location registrations in SQLite and maintains live WebSocket connections to one or more relay clients. When a tool call arrives from a cloud agent, the worker routes it to the appropriate relay client and streams the result back.

**Multi-location support:** Multiple relay clients can connect simultaneously, each representing a different physical location (home lab, branch office, customer site). Read-only tool calls are automatically fanned out to all connected locations and results are aggregated. Write operations require an explicit `__location` argument to target a specific site — useful for MSP workflows.

---

## Quick Start

### Install

Node.js 22 or newer is required.

```bash
curl -fsSL https://raw.githubusercontent.com/sirkirby/unifi-mcp/main/apps/worker/install.sh | bash
```

Or install the CLI directly:

```bash
npm install -g unifi-mcp-worker
unifi-mcp-worker install
```

The CLI will:
1. Check prerequisites (Node.js, Wrangler)
2. Deploy the worker to your Cloudflare account
3. Generate and set authentication tokens
4. Display your tokens and next steps

### Upgrade

```bash
unifi-mcp-worker upgrade
```

### Add a Location

```bash
unifi-mcp-worker add-location
```

### Manage Tokens

```bash
unifi-mcp-worker rotate-tokens
unifi-mcp-worker status
```

`rotate-tokens` does not print the new secret. It saves it to `~/.unifi-mcp-worker/config.json` (mode `0600`) and shows a masked value and the config key to read it from.

### Remove

```bash
unifi-mcp-worker destroy
```

---

## Configuration Reference

### Secrets

| Secret | Purpose |
|--------|---------|
| `AGENT_TOKEN` | Bearer token for cloud agents calling the `/mcp` endpoint. Grants every tool at every location; use [scoped agent tokens](#scoped-agent-tokens) for anything narrower |
| `ADMIN_TOKEN` | Bearer token required for admin API calls (`/api/*`) |

Secrets are set automatically by the CLI and can be rotated with `unifi-mcp-worker rotate-tokens`.

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TOOL_REGISTRATION_MODE` | `lazy` | Tool registration mode sent to relay clients. `lazy` registers only meta-tools (~200 tokens); `eager` registers all tools upfront (~5,000 tokens) |
| `CORS_ALLOWED_ORIGINS` | unset | Comma-separated browser origins (for example `https://app.example.com,http://localhost:5173`) allowed to read Worker responses cross-origin. Unset or empty echoes any request Origin; set it to restrict browser access to the listed origins |

Variables are set in `wrangler.toml` under `[vars]` or overridden via the Cloudflare dashboard. `wrangler deploy` (and so `unifi-mcp-worker upgrade`) replaces dashboard variables with `wrangler.toml`, so set `CORS_ALLOWED_ORIGINS` as a secret, which survives deploys:

```bash
echo "https://app.example.com" | wrangler secret put CORS_ALLOWED_ORIGINS --name <worker-name>
```

Once the list is set, only an origin on it gets `Access-Control-Allow-Origin`; any other origin, a missing Origin, and the opaque `null` origin, including on a preflight, get no CORS headers and the browser refuses the response. Allowed origins may send the Streamable HTTP `Mcp-Session-Id` and `MCP-Protocol-Version` headers and read `Mcp-Session-Id` back.

---

## API Reference

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/health` | GET | None | Health check — returns `{"status":"ok"}` |
| `/mcp` | POST | `AGENT_TOKEN` or a scoped agent token | MCP JSON-RPC endpoint for cloud agents |
| `/ws` | GET | `relay_token` | WebSocket upgrade for relay client connections |
| `/api/locations` | GET | `ADMIN_TOKEN` | List registered locations and connection status |
| `/api/locations/token` | POST | `ADMIN_TOKEN` | Generate a relay token for a new location |
| `/api/agent-tokens` | GET | `ADMIN_TOKEN` | List scoped agent tokens (never the secrets) |
| `/api/agent-tokens` | POST | `ADMIN_TOKEN` | Mint or rotate a scoped agent token |
| `/api/agent-tokens/<token_id or name>` | DELETE | `ADMIN_TOKEN` | Revoke a scoped agent token |

### MCP Endpoint

The `/mcp` endpoint accepts standard MCP JSON-RPC requests:

```bash
curl -X POST https://your-worker.workers.dev/mcp \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### Built-in Meta-Tools

The relay always exposes these meta-tools regardless of registration mode:

| Tool | Purpose |
|------|---------|
| `unifi_tool_index` | List all available UniFi tools with optional category or search filter |
| `unifi_execute` | Execute any UniFi tool by name; use `__location` to target a specific site |
| `unifi_batch` | Execute multiple UniFi tools in a single request |
| `unifi_location_timeline` | Collect bounded Network and Protect incident evidence with explicit per-source failures |

These names belong to the relay. The Network server's own `unifi_tool_index`,
`unifi_execute` and `unifi_batch`, and the `unifi_batch_status` and
`unifi_batch_cancel` that serve its batch jobs, are left out of the relay's
catalog; the relay's tools above cover them.

The timeline tool accepts `start`/`end` with UTC offsets, exact `device_macs`
and `camera_ids`, explicit `mappings`, and `max_window_seconds`, `max_events`,
`max_calls`, `max_elapsed_ms`. `products` defaults to Network and Protect;
requested Access collection is unsupported. `location_id` selects one location by
its UUID (from the location list, not its name) and an unknown one is refused before any read;
a call reads at most 7 sources (locations × products, one Protect source per
camera ID) and refuses a larger selection before any read.
It returns `data` as the [client view](../../docs/incident-evidence.md#client-view) of one combined
[incident evidence document](../../docs/incident-evidence.md#relay-and-worker-consumers), or the whole
document with `detail: "full"`; `max_records_returned` (1 to 50, default 25) sets the citations in the view,
which fits one tool result, and `resume_after` (the view's `record_selection.next_cursor`) reads the records after it.
Check `overall`, `coverage_complete`, source outcomes and exhausted budgets;
missing or failed sources are retained. Conflicting source IDs fail combination,
including across locations. Legacy area/name filters and `start_time`/`end_time`
are no longer supported.

---

## Token Management

The CLI manages tokens automatically during `install` and `rotate-tokens`. You can also manage tokens manually via the admin API:

```bash
curl -X POST https://your-worker.workers.dev/api/locations/token \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"location_name": "Home Lab"}'
```

Response:

```json
{
  "location_id": "a1b2c3d4-...",
  "location_name": "Home Lab",
  "token": "<relay-token>"
}
```

Store the `token` value securely — it is only returned once. Provide it to the Relay sidecar as `UNIFI_RELAY_TOKEN` (see the [Relay sidecar setup](https://github.com/sirkirby/unifi-mcp/tree/main/packages/unifi-mcp-relay)).

### List Registered Locations

```bash
unifi-mcp-worker status
```

Or via the admin API:

```bash
curl https://your-worker.workers.dev/api/locations \
  -H "Authorization: Bearer <admin-token>"
```

Response includes `connected: true/false` indicating whether the relay client WebSocket is currently active.

### Scoped Agent Tokens

`AGENT_TOKEN` grants every tool at every location. To give an agent less, mint a scoped agent token with the admin API. It is read-only unless you pass `"read_only": false`, and covers every location unless you list some:

```bash
curl -X POST https://your-worker.workers.dev/api/agent-tokens \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "dashboards", "read_only": true, "locations": ["Home Lab"]}'
```

Response:

```json
{
  "token_id": "e5f6a7b8-...",
  "name": "dashboards",
  "read_only": true,
  "locations": ["a1b2c3d4-..."],
  "token": "<agent-token>"
}
```

`locations` takes location names or IDs and stores IDs; an unknown location is refused. The `token` is returned only once and stored as a SHA-256 hash. Use it as the agent's bearer on `/mcp` exactly like `AGENT_TOKEN`. Minting the same `name` again rotates its secret and replaces its scope. Revoke it with `DELETE /api/agent-tokens/<token_id or name>`.

The Worker enforces the scope itself, before a call reaches a relay client:

- **Read-only:** only tools a location registers with `readOnlyHint: true` run. Any other tool, including through `unifi_execute` and `unifi_batch`, returns an error, as does a read fan-out where one location annotates the same tool as a write. `unifi_tool_index` and the `eager` tool list show only read-only tools.
- **Locations:** the token sees and calls only its locations. Tools registered elsewhere read as not found, a `__location` outside the scope is refused, read fan-out stays inside the scope, and `unifi_location_timeline` reads only those locations. A token scoped to one location routes like a single-location deployment, so writes need no `__location`.

Read-only depends on the tool annotations each relay client registers, so keep the LAN servers' own permission settings as the second layer.

---

## Connecting Cloud Agents

Use a client that supports MCP JSON-RPC over HTTP POST and a custom bearer authorization header:

- **Endpoint:** `https://your-worker.workers.dev/mcp`
- **Auth:** `Authorization: Bearer <agent-token>` (`AGENT_TOKEN` or a [scoped agent token](#scoped-agent-tokens))
- **Transport:** HTTP POST (standard MCP JSON-RPC)

Configure the bearer header explicitly in your client. MCP support alone does not establish compatibility with this relay's authentication and transport.

ChatGPT cannot connect to this authenticated relay as currently implemented: it requires OAuth for authenticated MCP servers and cannot send a custom API key. The Worker currently uses a static bearer token and does not implement OAuth. See [OpenAI's authentication requirements](https://developers.openai.com/plugins/build/auth) and [the relay OAuth tracking issue](https://github.com/sirkirby/unifi-mcp/issues/256).

### Multi-Location Writes

When multiple relay clients are connected, write operations require a `__location` argument passed to `unifi_execute`:

```json
{
  "tool": "block_client",
  "arguments": { "mac": "aa:bb:cc:dd:ee:ff" },
  "__location": "a1b2c3d4-..."
}
```

`__location` takes a location ID, not a name. Whenever it is supplied, with one
location or several, it must name a location that has the tool; anything else,
an empty value included, is refused with the ID and name of each location that
does. Leave it out, or send `null`, to name no location.

Read-only operations (tools with `readOnlyHint: true`) are automatically fanned out to all connected locations and results are returned as an aggregated response.

---

## Security

- **Timing-safe token comparison** — all token validation uses constant-time comparison to prevent timing attacks
- **SHA-256 hashed storage** — relay tokens and scoped agent tokens are stored as hashes in SQLite; the plaintext is never persisted
- **Scoped agent tokens** — read-only and per-location agent tokens are enforced by the Worker, not only by the LAN servers
- **CORS allowlist** — set `CORS_ALLOWED_ORIGINS` to let browsers read responses only from the listed origins; unset, any origin is echoed
- **Per-location isolation** — each relay client is identified by its own relay token and location ID; locations cannot access each other's data
- **HTTPS/WSS transport** — all traffic is encrypted in transit; Cloudflare terminates TLS at the edge
- **No credentials in config** — tokens and secrets are managed via the CLI or `wrangler secret put`, never committed to source

---

## Related

- [unifi-mcp](https://github.com/sirkirby/unifi-mcp) — source repository for this worker, the UniFi MCP servers, and the `unifi-mcp-relay` client
