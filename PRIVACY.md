# Privacy Policy

**Last updated:** 2026-06-12

## Summary

UniFi MCP does not collect, store, or transmit your personal data. All communication stays between your AI agent and your local UniFi controller. We have no servers, no analytics, no telemetry, and no tracking.

## How UniFi MCP Works

UniFi MCP is a set of [Model Context Protocol](https://modelcontextprotocol.io/) servers that run **locally on your machine**. They connect directly to your UniFi controller on your local network. Your AI agent (Claude Code, Claude Cowork, or other MCP clients) communicates with the MCP server over a local stdio or HTTP connection.

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

All data stays on your machine and your local network:

1. Your AI agent sends a tool call to the MCP server (running locally)
2. The MCP server queries your UniFi controller over your local network (HTTPS)
3. The controller responds with the requested data
4. The MCP server formats and returns the result to your AI agent

**No data leaves your network.**

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

## Third-Party Services

| Service | When Used | What It Sees |
|---------|-----------|-------------|
| **Your UniFi Controller** | Always | Tool requests (queries, mutations) over your local network |
| **Cloudflare Workers** | Only if you enable relay mode | Tool calls in transit (encrypted, not stored) |
| **PyPI** | Only during installation | Standard package download (pip/uv install) |
| **GitHub** | Only during plugin installation | Plugin source code download |

We do not integrate with any analytics, advertising, or data broker services.

## Your Controller Credentials

- Credentials are stored in your local environment variables, `.env` file, or Claude Code `settings.json`
- They are read at startup and used to authenticate with your controller
- They are never logged, transmitted externally, or stored in any persistent database
- API keys (if used) follow the same local-only pattern

MCP and API responses redact known controller secret fields by default, including Wi-Fi passphrases, VPN private or preshared keys, whole VPN configuration blobs (imported WireGuard/OpenVPN config files, which embed private keys and certificates), API tokens, Protect stream URLs/aliases, and credential token/PIN values. Redaction is controlled by policy, not per request: keep `UNIFI_REDACT_SENSITIVE_FIELDS=true` for normal AI-agent use, and set the global flag or a server-specific override such as `UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS=false`, `UNIFI_PROTECT_REDACT_SENSITIVE_FIELDS=false`, `UNIFI_ACCESS_REDACT_SENSITIVE_FIELDS=false`, or `UNIFI_API_REDACT_SENSITIVE_FIELDS=false` only for trusted local administration workflows that require raw secret values.

Redaction targets secret/credential material, not hardware inventory. Some read-only tools — for example switch port statistics (`unifi_get_port_stats`) — return physical device identifiers such as SFP/transceiver module serial numbers by default, because they are needed for legitimate inventory and audit workflows. These identifiers are not treated as secrets and are not redacted.

## Data Retention

UniFi MCP stores **nothing**. There is no database, no cache, no log files, and no session state. All data lives on your UniFi controller. When the MCP server process stops, no data persists.

## Children's Privacy

UniFi MCP is infrastructure management software intended for network administrators. It is not directed at children under 13 and does not knowingly collect information from children.

## Changes to This Policy

If we change this privacy policy, we will update the "Last updated" date at the top and commit the change to the repository. Since UniFi MCP has no data collection, changes would only reflect new features (like the relay) or clarifications.

## Contact

For privacy questions, reach the maintainer via the [GitHub repository](https://github.com/sirkirby/unifi-mcp) or the email listed on the [maintainer's profile](https://github.com/sirkirby).
