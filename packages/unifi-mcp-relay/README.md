# UniFi MCP Relay

A sidecar process that bridges locally-hosted MCP servers to the [Cloudflare Worker relay gateway](https://github.com/sirkirby/unifi-mcp/tree/main/apps/worker), enabling cloud agents (Claude, ChatGPT connectors, n8n, etc.) to access your UniFi MCP tools without exposing local ports.

## How It Works

```
Cloud Agent (Claude, n8n, ...)
    |
    v  MCP over HTTPS
    |
Cloudflare Worker (relay gateway)
    |
    v  WebSocket (persistent, authenticated)
    |
unifi-mcp-relay (this sidecar, runs on your LAN)
    |
    v  MCP over HTTP (Streamable HTTP transport)
    |
Local MCP Servers (network, protect, access)
```

The relay sidecar:

1. **Discovers** tools from your local MCP servers via the MCP protocol
2. **Connects** to the Cloudflare Worker via WebSocket with token authentication
3. **Registers** your location name and full tool catalog (including annotations)
4. **Forwards** tool calls from cloud agents to the correct local server
5. **Refreshes** the catalog periodically with change detection

## Quick Start

### Environment Variables

```bash
# Required
UNIFI_RELAY_URL=https://your-worker.workers.dev     # Cloudflare Worker URL
UNIFI_RELAY_TOKEN=your-relay-token                   # Generated via worker admin API
UNIFI_RELAY_LOCATION_NAME=Home Lab                   # Friendly name for this location

# Optional
UNIFI_RELAY_SERVERS=http://localhost:3000,http://localhost:3001  # MCP server URLs (default: http://localhost:3000)
UNIFI_RELAY_REFRESH_INTERVAL=300                     # Catalog refresh interval in seconds (default: 300)
UNIFI_RELAY_RECONNECT_MAX_DELAY=60                   # Max reconnect backoff in seconds (default: 60)
```

### Run with pip

```bash
pip install unifi-mcp-relay
unifi-mcp-relay
```

### Run with Docker

```bash
docker run --rm \
  -e UNIFI_RELAY_URL=https://your-worker.workers.dev \
  -e UNIFI_RELAY_TOKEN=your-token \
  -e UNIFI_RELAY_LOCATION_NAME="Home Lab" \
  -e UNIFI_RELAY_SERVERS=http://host.docker.internal:3000 \
  ghcr.io/sirkirby/unifi-mcp-relay:latest
```

### Run with Docker Compose

The relay is included in the project's `docker/docker-compose.yml` behind a profile:

```bash
docker compose --profile relay up
```

## Prerequisites

Before running the relay, you need:

1. **Deploy the Cloudflare Worker** using the CLI:
   ```bash
   npm install -g unifi-mcp-worker
   unifi-mcp-worker install
   ```
   This deploys the relay gateway and generates your authentication tokens.

2. **Local MCP servers** running with HTTP transport enabled (`UNIFI_MCP_HTTP_ENABLED=true`)

## Multi-Location Support

The relay + worker architecture supports multiple locations. Each location runs its own relay sidecar with a unique token and location name. The worker:

- **Read-only tools** are fanned out to all locations and results aggregated
- **Write tools** require an explicit `__location` argument to target a specific location
- **Tool discovery** is deduplicated across locations in the worker's tool index

## Architecture

The relay is a standalone Python package with no dependency on the MCP server packages. It communicates with local servers purely via the MCP HTTP transport protocol.

| Module | Purpose |
|--------|---------|
| `config.py` | Environment variable loading and validation |
| `protocol.py` | WebSocket message types (register, tool_call, heartbeat, etc.) |
| `discovery.py` | MCP protocol tool discovery from local servers |
| `forwarder.py` | Tool call routing to the correct local server |
| `client.py` | WebSocket client with reconnection and auth |
| `main.py` | Orchestrator wiring discovery, forwarding, and the client |

## Development

```bash
# Run tests
make relay-test

# Run the relay locally
python -m unifi_mcp_relay
```
