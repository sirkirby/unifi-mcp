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
                                                   unifi-mcp-relay (local network)
                                                                |
                                                    UniFi MCP Server (stdio/HTTP)
```

The Durable Object persists location registrations in SQLite and maintains live WebSocket connections to one or more relay clients. When a tool call arrives from a cloud agent, the worker routes it to the appropriate relay client and streams the result back.

**Multi-location support:** Multiple relay clients can connect simultaneously, each representing a different physical location (home lab, branch office, customer site). Read-only tool calls are automatically fanned out to all connected locations and results are aggregated. Write operations require an explicit `__location` argument to target a specific site — useful for MSP workflows.

---

## Quick Start

### Install

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

### Remove

```bash
unifi-mcp-worker destroy
```

---

## Configuration Reference

### Secrets

| Secret | Purpose |
|--------|---------|
| `AGENT_TOKEN` | Bearer token required by cloud agents calling the `/mcp` endpoint |
| `ADMIN_TOKEN` | Bearer token required for admin API calls (`/api/*`) |

Secrets are set automatically by the CLI and can be rotated with `unifi-mcp-worker rotate-tokens`.

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TOOL_REGISTRATION_MODE` | `lazy` | Tool registration mode sent to relay clients. `lazy` registers only meta-tools (~200 tokens); `eager` registers all tools upfront (~5,000 tokens) |

Variables are set in `wrangler.toml` under `[vars]` or overridden via the Cloudflare dashboard.

---

## API Reference

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/health` | GET | None | Health check — returns `{"status":"ok"}` |
| `/mcp` | POST | `AGENT_TOKEN` | MCP JSON-RPC endpoint for cloud agents |
| `/ws` | GET | `relay_token` | WebSocket upgrade for relay client connections |
| `/api/locations` | GET | `ADMIN_TOKEN` | List registered locations and connection status |
| `/api/locations/token` | POST | `ADMIN_TOKEN` | Generate a relay token for a new location |

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
| `unifi_location_timeline` | Query a unified event timeline across connected locations and products |

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

Store the `token` value securely — it is only returned once. Provide it to `unifi-mcp-relay` as `UNIFI_MCP_RELAY_TOKEN` (see [unifi-mcp](https://github.com/sirkirby/unifi-mcp) for relay client configuration).

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

---

## Connecting Cloud Agents

Point any MCP-compatible client at the worker URL:

- **Endpoint:** `https://your-worker.workers.dev/mcp`
- **Auth:** `Authorization: Bearer <agent-token>`
- **Transport:** HTTP POST (standard MCP JSON-RPC)

Compatible clients include Claude connectors, ChatGPT plugins, n8n MCP nodes, and any platform that supports the MCP protocol over HTTP.

### Multi-Location Writes

When multiple relay clients are connected, write operations require a `__location` argument passed to `unifi_execute`:

```json
{
  "tool_name": "block_client",
  "arguments": { "mac": "aa:bb:cc:dd:ee:ff" },
  "__location": "a1b2c3d4-..."
}
```

Read-only operations (tools with `readOnlyHint: true`) are automatically fanned out to all connected locations and results are returned as an aggregated response.

---

## Security

- **Timing-safe token comparison** — all token validation uses constant-time comparison to prevent timing attacks
- **SHA-256 hashed storage** — relay tokens are stored as hashes in SQLite; the plaintext is never persisted
- **Per-location isolation** — each relay client is identified by its own relay token and location ID; locations cannot access each other's data
- **HTTPS/WSS transport** — all traffic is encrypted in transit; Cloudflare terminates TLS at the edge
- **No credentials in config** — tokens and secrets are managed via the CLI or `wrangler secret put`, never committed to source

---

## Related

- [unifi-mcp](https://github.com/sirkirby/unifi-mcp) — source repository for this worker, the UniFi MCP servers, and the `unifi-mcp-relay` client
