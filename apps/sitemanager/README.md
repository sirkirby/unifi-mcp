# UniFi Site Manager MCP Server

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server for Ubiquiti's official [Site Manager API](https://developer.ui.com/site-manager-api/). It gives an AI assistant the account-wide view that the Network, Protect and Access servers cannot see from inside one console: every host, site and device on a UI account, WAN performance per site, and SD-WAN configurations.

## This server talks to Ubiquiti's cloud

The other servers in this project connect directly to a console you name. This one is different:

- Every request goes to `https://api.ui.com`. The destination is fixed and cannot be changed by configuration.
- It authenticates with a Site Manager API key, which covers every console the account can see.
- It is read-only. The Site Manager API has no write operations, and neither does this server.

## Quick start

1. Create an API key at [unifi.ui.com](https://unifi.ui.com) under Settings > API Keys.
2. Set it and start the server:

```bash
export UNIFI_SITEMANAGER_API_KEY=your-key
uvx unifi-sitemanager-mcp
```

Without a key the server still starts. It answers the client in setup mode and explains what to set.

### Claude Desktop

```json
{
  "mcpServers": {
    "unifi-sitemanager": {
      "command": "uvx",
      "args": ["unifi-sitemanager-mcp"],
      "env": { "UNIFI_SITEMANAGER_API_KEY": "your-key" }
    }
  }
}
```

## Tools

Nine read-only tools. See [docs/tools.md](docs/tools.md).

| Tool | What it returns |
|---|---|
| `sitemanager_list_hosts` | Consoles and self-hosted servers on the account |
| `sitemanager_get_host` | One host, optionally with its full reported state |
| `sitemanager_list_sites` | Sites across every host, with counts and WAN health |
| `sitemanager_list_devices` | Devices grouped by host, with firmware status |
| `sitemanager_get_isp_metrics` | WAN performance for every site |
| `sitemanager_query_isp_metrics` | WAN performance for named sites |
| `sitemanager_list_sdwan_configs` | SD-WAN configurations |
| `sitemanager_get_sdwan_config` | One SD-WAN configuration |
| `sitemanager_get_sdwan_config_status` | Deployment status of one SD-WAN configuration |

Host, site and device ids returned here belong to the Site Manager tool family. They are not the ids the Network, Protect or Access servers use.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_SITEMANAGER_API_KEY` | none | Site Manager API key. Also accepted as `UNIFI_SITEMANAGER_API_KEY_FILE` or `UNIFI_SITEMANAGER_API_KEY_COMMAND`. |
| `UNIFI_SITEMANAGER_TIMEOUT_SECONDS` | `30` | Seconds to wait for one API response. |
| `UNIFI_SITEMANAGER_REDACT_SENSITIVE_FIELDS` | `true` | Redact secret-looking fields in responses. |
| `UNIFI_TOOL_REGISTRATION_MODE` | `lazy` | `lazy`, `eager` or `meta_only`. |

The key is read only from `UNIFI_SITEMANAGER_API_KEY`. The server does not use `UNIFI_API_KEY`: that variable holds a console's local key, which must never be sent to the cloud. See [docs/configuration.md](docs/configuration.md).

## Remote access

The server can be listed in a relay's `UNIFI_RELAY_SERVERS` like the others, but it is not added by default. Relay tokens are scoped to a location, and this server exposes the whole account: anyone holding a token for that location, including a read-only one, could then read the inventory of every console on the account.

## Limits

- The API allows 10,000 requests per minute. When it answers 429 the server waits briefly for a read, then reports the retry time.
- A personal API key lists consoles the account owns or has been invited to.
- List tools return one page at a time and never crawl every page on their own.

## More

- [Tools](docs/tools.md)
- [Configuration](docs/configuration.md)
- [Permissions](docs/permissions.md)
- [Troubleshooting](docs/troubleshooting.md)
