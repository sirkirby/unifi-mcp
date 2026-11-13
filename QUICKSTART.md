# Quick Start

UniFi MCP ships independent MCP servers for Network, Protect, and Access, a
read-only Site Manager server for a whole UniFi cloud account, an HTTP API for
custom applications, and optional Cloud Relay components for remote MCP
clients.

This guide starts with the MCP servers. If you are building software that
integrates over HTTP, including an automation service or MCP adapter, start
with the [`unifi-api-server` quickstart](apps/api/README.md#quickstart). If an
MCP client needs remote access to local servers, use the Cloud Relay section
below.

For agent-guided setup, native plugin marketplaces, product-scoped
`npx skills add` commands, OpenCode, Antigravity, Cursor, and Devin Desktop, see
[Install UniFi MCP with an agent](docs/agent-install.md).

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

## Site Manager (cloud account)

The Site Manager server is separate from the three console servers. It needs
no console host or login: it reads every host, site and device on a UI account
through Ubiquiti's cloud API at `https://api.ui.com`, using one Site Manager API
key. Every request goes to that fixed cloud address, even when your client runs
the server locally over stdio.

It is not published yet. Create an API key at [unifi.ui.com](https://unifi.ui.com)
under Settings > API Keys, save it in a file only you can read, and run the
server from a [source checkout](#source-checkout):

```bash
export UNIFI_SITEMANAGER_API_KEY_FILE="$HOME/.config/unifi-mcp/sitemanager-api-key"
uv run --package unifi-sitemanager-mcp unifi-sitemanager-mcp
```

Set exactly one of `UNIFI_SITEMANAGER_API_KEY`, `UNIFI_SITEMANAGER_API_KEY_FILE`
or `UNIFI_SITEMANAGER_API_KEY_COMMAND`. The server never uses `UNIFI_API_KEY`
or the other `UNIFI_*` variables above. Stdio is the default; HTTP is opt-in
and listens on port 3003. See the [Site Manager README](apps/sitemanager/README.md).

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

The other servers run the same way with their own package names, for example
`uv run --package unifi-sitemanager-mcp unifi-sitemanager-mcp`.

## Optional Cloud Relay

Use the relay when a cloud-hosted agent needs to reach MCP servers running on your local network without opening inbound ports. The relay does not include the Site Manager server unless you add it to `UNIFI_RELAY_SERVERS` yourself; a relay token for that location would then read the whole cloud account.

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
