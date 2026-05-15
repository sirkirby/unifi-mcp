# Security Policy

## Supported Versions

| Package | Supported Versions |
|---------|-------------------|
| unifi-network-mcp | Latest release |
| unifi-protect-mcp | Latest release (beta) |
| unifi-access-mcp | Latest release (beta) |
| unifi-mcp-relay | Latest release (beta) |
| unifi-mcp-worker | Latest release (beta) |

Only the latest release of each package receives security patches. We recommend always running the most recent version.

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

### Primary Channel: GitHub Security Advisories

1. Go to the [Security Advisories page](https://github.com/sirkirby/unifi-mcp/security/advisories)
2. Click "Report a vulnerability"
3. Provide as much detail as possible:
   - Description of the vulnerability
   - Steps to reproduce
   - Affected versions
   - Potential impact

### Fallback: Email

If you are unable to use GitHub Security Advisories, email security concerns to the repository maintainer via the email listed on the [GitHub profile](https://github.com/sirkirby).

### Response Timeline

- **Acknowledgment:** Within 72 hours of report
- **Triage:** Within 7 days — we will confirm the vulnerability, assess severity, and communicate next steps
- **Fix:** Coordinated 90-day disclosure window from the date of report
- **Disclosure:** Security advisory published after fix is released, or after 90 days if no fix is available

### Credit

Reporters will be credited in the security advisory and CHANGELOG unless they request anonymity.

## Security Model

UniFi MCP is designed with a **secure-by-default** posture:

### Local-First Authentication

- Credentials (username/password) are used to authenticate directly with your local UniFi controller
- Credentials never leave your network — they are not sent to any external service
- API key authentication is supported as an experimental additive option
- The relay sidecar connects to a Cloudflare Worker via token-scoped WebSocket — no inbound ports are exposed

### Permission System

- **Confirm-by-default** for all mutations (create, update, delete) — human approval required before execution
- **Policy gates** (`UNIFI_POLICY_*` env vars) provide hard boundaries to disable specific actions when needed
- Read-only operations are always allowed
- All tools are always visible and discoverable in the tool index — authorization is enforced at call time
- Tools denied by policy gates return a clear error with guidance on how to enable

### Preview-Before-Confirm

- All state-changing operations use a two-step flow: preview first, then confirm
- Default call returns a preview of what would change
- Explicit `confirm=True` is required to execute the mutation
- `UNIFI_TOOL_PERMISSION_MODE=bypass` can bypass this for automation workflows

### No Persistent Storage

- All state lives on the UniFi controller — the MCP server stores nothing locally
- No database, no cache, no session files
- Configuration is read from environment variables and config YAML at startup

## Known Controller Vulnerabilities

These are vulnerabilities in Ubiquiti's UniFi controller software, **not in this MCP server**. We document them here so users can verify their controllers are patched.

| CVE | CVSS | Affected Product | Affected Versions | Fixed In | Notes |
|-----|------|-----------------|-------------------|----------|-------|
| CVE-2026-22557 | 10.0 | UniFi Network | 10.0.x | See [Ubiquiti Advisory](https://community.ui.com/releases) | Critical — update immediately |

### Minimum Compatible Controller Versions

We recommend running at least these controller versions for security and API compatibility:

| Product | Minimum Version | Recommended |
|---------|----------------|-------------|
| UniFi Network | 8.6+ | Latest stable |
| UniFi Protect | 5.0+ | Latest stable |
| UniFi Access | 2.0+ | Latest stable |

## Scope

### In Scope

- MCP server code (`apps/network/`, `apps/protect/`, `apps/access/`)
- Shared packages (`packages/unifi-core/`, `packages/unifi-mcp-shared/`)
- Relay sidecar (`packages/unifi-mcp-relay/`)
- Cloudflare Worker relay and CLI (`apps/worker/`)
- Claude Code plugins (`plugins/`)

### Out of Scope

The following are **not** maintained by this project. Report issues to their respective maintainers:

- UniFi controller firmware (report to [Ubiquiti](https://community.ui.com))
- [aiounifi](https://github.com/Kane610/aiounifi) library
- [pyunifiprotect](https://github.com/uilibs/uiprotect) library
- [py-unifi-access](https://github.com/sirkirby/py-unifi-access) library
- MCP protocol specification (report to [modelcontextprotocol](https://github.com/modelcontextprotocol/specification))
