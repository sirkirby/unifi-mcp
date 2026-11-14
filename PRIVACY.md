# Privacy Policy

**Last updated:** 2026-11-12

## Summary

UniFi MCP does not collect, store, or transmit your personal data to us. The Network, Protect and Access servers talk only to your local UniFi controller. The Site Manager server is the exception: it sends its requests, and its API key, to Ubiquiti's cloud API at `https://api.ui.com` (see [Site Manager cloud requests](#site-manager-cloud-requests)). We have no servers, no analytics, no telemetry, and no tracking.

## How UniFi MCP Works

UniFi MCP is a set of [Model Context Protocol](https://modelcontextprotocol.io/) servers that run **locally on your machine**. The Network, Protect and Access servers connect directly to your UniFi controller on your local network; the Site Manager server connects to Ubiquiti's cloud instead. Your AI agent (Claude Code, Claude Cowork, or other MCP clients) communicates with the MCP server over a local stdio or HTTP connection.

```
Your AI Agent <--local--> MCP Server (on your machine) <--your network--> UniFi Controller
```

## What We Don't Collect

- **No telemetry.** We do not collect usage data, error reports, or analytics of any kind.
- **No network traffic.** We do not monitor, log, or transmit your network traffic or device data.
- **No credentials.** Your UniFi username, password, and API keys are stored only in your local environment variables or config files. They are never sent to us or any third party.
- **No personal data.** We do not collect names, email addresses, IP addresses, or any identifying information.
- **No cookies or tracking.** There is no web interface, no cookies, no tracking pixels.

## Data Flow

### Local Mode (default)

For the Network, Protect and Access servers, all data stays on your machine and your local network:

1. Your AI agent sends a tool call to the MCP server (running locally)
2. The MCP server queries your UniFi controller over your local network (HTTPS)
3. The controller responds with the requested data
4. The MCP server formats and returns the result to your AI agent

**No data leaves your network.**

### Site Manager cloud requests

The Site Manager server is not local-first. Even when your MCP client runs it on your machine over local stdio, every tool call becomes a request to Ubiquiti's cloud:

```
Your AI Agent <--local--> Site Manager server (on your machine) <--internet--> Ubiquiti api.ui.com
```

1. Your AI agent sends a tool call to the Site Manager server
2. The server sends a request with your Site Manager API key to `https://api.ui.com`. That destination is fixed in the code and cannot be configured
3. Ubiquiti returns data about your UI account: hosts, sites, devices, WAN metrics and SD-WAN configurations, which the server passes back to your AI agent

**In Site Manager mode:**
- Ubiquiti sees the API key and each request, under Ubiquiti's own privacy terms
- The key is account-wide: it reads every console on the UI account, not one console
- The key is never taken from, or shared with, the console credentials the other servers use, and no console credential is sent to the cloud
- The server is read-only and stores nothing; the account holder's name, email and role are never returned to the agent
- The Cloud Relay does not include this server by default. If you add it to the relay, a relay token for that location can read the whole account

### Relay Mode (optional)

If you choose to enable the [cloud relay](packages/unifi-mcp-relay/), your tool calls are proxied through a Cloudflare Worker:

1. Your local relay sidecar connects **outbound** to the Cloudflare Worker via WebSocket
2. Tool calls from remote agents are forwarded through the Worker to your local sidecar
3. The sidecar executes the call against your local UniFi controller and returns the result

**In relay mode:**
- The Cloudflare Worker processes tool calls in transit but does not store them
- Communication is encrypted (WSS/TLS)
- Access is scoped by a token you generate and control
- No inbound ports are exposed on your network
- You can revoke relay access at any time by rotating or deleting your token

### Trace Export (optional)

If you set an OTLP endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`), the MCP servers send trace spans to the collector you configured. Without an endpoint, no spans leave the server process. Retention follows your collector's settings.

- A span records the MCP method, the tool name, the JSON-RPC request ID and the timing, not tool arguments or results.
- A call through the meta tools (`unifi_execute`, `unifi_batch` and their Protect and Access counterparts), which the `lazy` and `meta_only` registration modes rely on, carries the meta tool's name, not the name of the tool it runs.
- A failed request records its error message in the span status. For `resources/read`, the SDK's message contains the requested resource URI, so a failed Protect camera snapshot read records the camera ID (`Error creating resource from template protect://cameras/<camera_id>/snapshot`).
- Tools return their errors as results. If an exception escapes a request handler anyway, the SDK also records its type, message and stack trace on the span.

## Third-Party Services

| Service | When Used | What It Sees |
|---------|-----------|-------------|
| **Your UniFi Controller** | Network, Protect and Access servers | Tool requests (queries, mutations) over your local network |
| **Ubiquiti Site Manager API (`api.ui.com`)** | Only if you run the Site Manager server | Your Site Manager API key and every read request it makes, over HTTPS |
| **Cloudflare Workers** | Only if you enable relay mode | Tool calls in transit (encrypted, not stored) |
| **Your OTLP collector** | Only if you set an OTLP endpoint | Trace spans: MCP method, tool name, request ID, timing, error messages of failed requests |
| **PyPI** | Only during installation | Standard package download (pip/uv install) |
| **GitHub** | Only during plugin installation | Plugin source code download |

We do not integrate with any analytics, advertising, or data broker services.

## Your Controller Credentials

- Credentials are stored in your local environment variables, `.env` file, or Claude Code `settings.json`
- They are read at startup and used to authenticate with your controller
- They are never logged, transmitted externally, or stored in any persistent database
- API keys (if used) follow the same local-only pattern
- The exception is the Site Manager API key: it is stored locally the same way, but the Site Manager server sends it to Ubiquiti's cloud API with every request, because that is the only place it works

MCP and API responses redact known controller secret fields by default, including Wi-Fi passphrases, VPN private or preshared keys, whole VPN configuration blobs (imported WireGuard/OpenVPN config files, which embed private keys and certificates), API tokens, device-SSH credentials and the site management key (the stored SSH password hash, management key and API token are reported only as present or absent), Protect stream URLs/aliases, and credential token/PIN values. Redaction is controlled by policy, not per request: keep `UNIFI_REDACT_SENSITIVE_FIELDS=true` for normal AI-agent use, and set the global flag or a server-specific override such as `UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS=false`, `UNIFI_PROTECT_REDACT_SENSITIVE_FIELDS=false`, `UNIFI_ACCESS_REDACT_SENSITIVE_FIELDS=false`, `UNIFI_SITEMANAGER_REDACT_SENSITIVE_FIELDS=false`, or `UNIFI_API_REDACT_SENSITIVE_FIELDS=false` only for trusted local administration workflows that require raw secret values.

Redaction targets secret/credential material, not hardware inventory. Some read-only tools — for example switch port statistics (`unifi_get_port_stats`) — return physical device identifiers such as SFP/transceiver module serial numbers by default, because they are needed for legitimate inventory and audit workflows. These identifiers are not treated as secrets and are not redacted.

## Data Retention

UniFi MCP stores **nothing**. There is no database, no cache, no log files, and no session state. All data lives on your UniFi controller, or for Site Manager on your UI account at Ubiquiti. When the MCP server process stops, no data persists.

## Children's Privacy

UniFi MCP is infrastructure management software intended for network administrators. It is not directed at children under 13 and does not knowingly collect information from children.

## Changes to This Policy

If we change this privacy policy, we will update the "Last updated" date at the top and commit the change to the repository. Since UniFi MCP has no data collection, changes would only reflect new features (like the relay) or clarifications.

## Contact

For privacy questions, reach the maintainer via the [GitHub repository](https://github.com/sirkirby/unifi-mcp) or the email listed on the [maintainer's profile](https://github.com/sirkirby).
