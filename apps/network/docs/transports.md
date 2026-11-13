# Transport Setup

The server supports three transport protocols. stdio is the default and recommended for most use cases.

## stdio (Default)

Used by Claude Desktop, LM Studio, and most MCP clients. No configuration needed.

```bash
# Direct
unifi-network-mcp

# Via uvx
uvx unifi-network-mcp@latest

# Docker (stdin_open required)
docker run -i --rm \
  -e UNIFI_HOST=192.168.1.1 \
  -e UNIFI_USERNAME=admin \
  -e UNIFI_PASSWORD=secret \
  ghcr.io/sirkirby/unifi-network-mcp:latest
```

### Claude Desktop Configuration

```jsonc
{
  "mcpServers": {
    "unifi": {
      "command": "uvx",
      "args": ["unifi-network-mcp"],
      "env": {
        "UNIFI_HOST": "192.168.1.1",
        "UNIFI_USERNAME": "admin",
        "UNIFI_PASSWORD": "your-password"
      }
    }
  }
}
```

### Docker with Claude Desktop

Option A: Claude launches the container:
```jsonc
{
  "mcpServers": {
    "unifi": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "UNIFI_HOST=192.168.1.1",
        "-e", "UNIFI_USERNAME=admin",
        "-e", "UNIFI_PASSWORD=secret",
        "ghcr.io/sirkirby/unifi-network-mcp:latest"
      ]
    }
  }
}
```

Option B: Attach to a running container (via docker-compose):
```bash
docker compose -f docker/docker-compose.yml up -d
```
```jsonc
{
  "mcpServers": {
    "unifi": {
      "command": "docker",
      "args": ["exec", "-i", "unifi-network-mcp", "unifi-network-mcp"]
    }
  }
}
```

### LM Studio

Edit `mcp.json` (chat prompt > tool icon > edit mcp.json) with the same structure as Claude Desktop config above. Use a tool-capable model like `gpt-oss`.

## Streamable HTTP

The current MCP spec default (2025-03-26). Uses a single `/mcp` endpoint.

```bash
# Enable
export UNIFI_MCP_HTTP_ENABLED=true
# Transport defaults to streamable-http

# Keep unauthenticated HTTP local; allow HTTP outside container PID 1
export UNIFI_MCP_HTTP_FORCE=true
export UNIFI_MCP_HOST=127.0.0.1
export UNIFI_MCP_PORT=3000
```

```bash
# Docker with HTTP
docker run -i --rm \
  -p 127.0.0.1:3000:3000 \
  -e UNIFI_MCP_HTTP_ENABLED=true \
  -e UNIFI_MCP_HOST=0.0.0.0 \
  -e UNIFI_HOST=192.168.1.1 \
  -e UNIFI_USERNAME=admin \
  -e UNIFI_PASSWORD=secret \
  ghcr.io/sirkirby/unifi-network-mcp:latest
```

The endpoint supports:
- **POST** `/mcp` — JSON-RPC requests
- **GET** `/mcp` — SSE event stream
- **DELETE** `/mcp` — Session termination

stdio and HTTP can run concurrently.

## SSE (Legacy)

For backwards compatibility with older MCP clients.

```bash
export UNIFI_MCP_HTTP_ENABLED=true
export UNIFI_MCP_HTTP_TRANSPORT=sse
```

Uses `/sse` (event stream) + `/messages/` (JSON-RPC) endpoints.

## HTTP Deployment Security

These instructions apply to Network, Protect, and Access (ports 3000, 3001, and 3002), and to Site Manager (port 3003). Docker Compose starts Site Manager only with the opt-in `sitemanager` profile, and the Cloud Relay does not reach it unless you add it to `UNIFI_RELAY_SERVERS`, after which any relay token for that location can read the whole account. Its HTTP endpoint exposes the inventory of every console on the UI account, so keep it on loopback and set a bearer token. MCP HTTP has no caller authentication unless you set the optional [bearer token](#http-bearer-token). Without it, every process that reaches the backend can invoke enabled tools with the server's controller privileges. Host/Origin validation and `confirm=True` do not authenticate callers or verify human approval.

Package defaults disable HTTP and bind to `127.0.0.1` when enabled. For an existing standalone container deployment, explicitly set `UNIFI_MCP_HTTP_ENABLED=true` and `UNIFI_MCP_HOST=0.0.0.0` inside the container, and publish only on host loopback as above. Recreate existing Compose services to apply the new loopback port mappings. Compose's relay still reaches the servers by service name on the trusted container network.

For remote clients, use Cloud Relay or an authenticated TLS reverse proxy. Restrict backend access to the proxy and trusted local processes/containers; do not expose backend ports on the LAN or internet. Use Docker Engine 28.0.0 or newer with normal NAT bridge networking; older engines and custom routing/network modes need additional firewall controls. See the [security model](../../../SECURITY.md#mcp-transport-trust-boundary).

## HTTP Bearer Token

Set `UNIFI_MCP_HTTP_AUTH_TOKEN` to make the HTTP transport refuse every request that does not carry `Authorization: Bearer <token>`. It covers every method on `/mcp`, and both `/sse` and `/messages/`; stdio is unaffected. A missing or wrong token gets `401` with `WWW-Authenticate: Bearer realm="unifi-mcp"`. Leaving it unset keeps today's behaviour.

```bash
export UNIFI_MCP_HTTP_ENABLED=true
export UNIFI_MCP_HTTP_AUTH_TOKEN="$(openssl rand -hex 32)"
```

- The token must be at least 32 printable ASCII characters with no whitespace; anything else refuses startup.
- A variable that is set but empty also refuses startup, rather than leaving HTTP unauthenticated, so a secret store that writes a missing secret as `""` cannot silently turn authentication off. To run without a token, unset the variable.
- `UNIFI_NETWORK_MCP_HTTP_AUTH_TOKEN`, `UNIFI_PROTECT_MCP_HTTP_AUTH_TOKEN`, `UNIFI_ACCESS_MCP_HTTP_AUTH_TOKEN` and `UNIFI_SITEMANAGER_MCP_HTTP_AUTH_TOKEN` override the shared value for one server, so each can have its own token.
- Like the controller password, it accepts `..._FILE` (a path holding the token, for Docker or Kubernetes secrets) or `..._COMMAND` (an argv whose stdout is the token), honoured only from the environment the server was started with.
- `server.http.auth_token` in a `CONFIG_PATH` YAML file is the lowest-precedence source; any of the environment spellings above wins over it.
- Clients send it as a header, for example `claude mcp add --transport http unifi http://127.0.0.1:3000/mcp --header "Authorization: Bearer $TOKEN"`.

The token is one static secret with no scopes or expiry. It authenticates the caller; it does not encrypt the connection, so carry it only over TLS or loopback. The intended shape is a TLS tunnel or reverse proxy (Cloudflare Tunnel, Tailscale, an ingress) forwarding to a backend that still binds loopback or a private container network. It does not replace the Host/Origin allowlist, policy gates, or `confirm=True`.

The Cloud Relay sidecar does not send a token to the local servers yet, so leave it unset on servers the relay reaches.

## Reverse Proxy

Configure authentication and TLS on Nginx, Cloudflare, or the Kubernetes ingress, and block every route that bypasses it. For SSE, protect both `/sse` and `/messages/`; for Streamable HTTP, protect every method on `/mcp`.

1. Add your domain to allowed hosts:
   ```bash
   export UNIFI_MCP_ALLOWED_HOSTS=localhost,127.0.0.1,unifi-mcp.example.com
   ```
   Docker Compose preserves this operator allowlist and separately adds the container-service hosts it requires. Recreate the services after changing the value.

2. Keep DNS rebinding protection enabled. Configure the proxy to forward an allowed Host header and configure allowed origins for browser clients. An allowed hostname does not replace authentication.

## Security Notes

- **stdio** is the safest transport — no network exposure
- **HTTP** should only be enabled in local development, behind authenticated reverse proxies, or with the [bearer token](#http-bearer-token) set and carried over TLS
- Leave HTTP disabled in production unless you understand the security implications
- HTTP starts for PID 1 only when explicitly enabled; use `UNIFI_MCP_HTTP_FORCE=true` for an opted-in local non-container process.
