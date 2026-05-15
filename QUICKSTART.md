# Quick Start

UniFi MCP ships independent MCP servers for Network, Protect, and Access, plus optional cloud relay components for cloud-hosted agents.

## Install A Server

For the Network server:

```bash
uvx unifi-network-mcp@latest
```

For Protect or Access:

```bash
uvx unifi-protect-mcp@latest
uvx unifi-access-mcp@latest
```

Configure the server with environment variables:

```bash
export UNIFI_HOST=192.168.1.1
export UNIFI_USERNAME=admin
export UNIFI_PASSWORD=password
```

Lazy tool registration is the default. You normally do not need to set `UNIFI_TOOL_REGISTRATION_MODE`.

## Claude Desktop

Example Network server configuration:

```json
{
  "mcpServers": {
    "unifi-network": {
      "command": "uvx",
      "args": ["unifi-network-mcp@latest"],
      "env": {
        "UNIFI_HOST": "192.168.1.1",
        "UNIFI_USERNAME": "admin",
        "UNIFI_PASSWORD": "password"
      }
    }
  }
}
```

Then restart Claude Desktop and ask for your available UniFi tools or devices.

## Source Checkout

For local development:

```bash
git clone https://github.com/sirkirby/unifi-mcp.git
cd unifi-mcp
make sync
make check
```

`make sync` installs the Python workspace plus the self-contained worker npm dependencies. `make check` runs formatting checks, linting, generated artifact drift checks, Python tests, worker tests, and the worker TypeScript typecheck.

Run the Network server from the checkout:

```bash
uv run --package unifi-network-mcp unifi-network-mcp
```

## Optional Cloud Relay

Use the relay when a cloud-hosted agent needs to reach MCP servers running on your local network without opening inbound ports.

Deploy the Cloudflare Worker gateway:

```bash
npm install -g unifi-mcp-worker
unifi-mcp-worker install
```

Then run the local relay sidecar:

```bash
pip install unifi-mcp-relay
export UNIFI_RELAY_URL=https://your-worker.workers.dev
export UNIFI_RELAY_TOKEN=your-relay-token
export UNIFI_RELAY_LOCATION_NAME="Home Lab"
unifi-mcp-relay
```

See [apps/worker](apps/worker/) and [packages/unifi-mcp-relay](packages/unifi-mcp-relay/) for relay details.

## More Documentation

- [README.md](README.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/cross-product.md](docs/cross-product.md)

## Support

- [Issues](https://github.com/sirkirby/unifi-mcp/issues)
- [Discussions](https://github.com/sirkirby/unifi-mcp/discussions)
