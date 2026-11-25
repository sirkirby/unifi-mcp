# Security Policy

## Supported Versions

| Package | Supported Versions |
|---------|-------------------|
| unifi-network-mcp | Latest release |
| unifi-protect-mcp | Latest release (beta) |
| unifi-access-mcp | Latest release (beta) |
| unifi-sitemanager-mcp | Latest release (beta) |
| unifi-innerspace-mcp | Latest release (beta) |
| unifi-drive-mcp | Latest release (beta) |
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
- Credentials are sent to the controller explicitly configured by the operator; the launcher and its configuration must be trusted
- Credentials can be kept out of the MCP client's environment with `UNIFI_<SERVER>_PASSWORD_FILE` or `UNIFI_<SERVER>_PASSWORD_COMMAND`; both indirections are honoured only for variables present in the environment the server was started with. The command provider's platform, executable-resolution and process-lifecycle contract is in [docs/credential-providers.md](docs/credential-providers.md)
- MCP servers never automatically load `.env` files or working-directory YAML. Custom YAML requires an explicit absolute `CONFIG_PATH` in the process environment. The only settings file read is the one named by `UNIFI_SETTINGS_FILE` in the process environment: it must be an absolute path, owned by the current user and not group- or world-writable (POSIX), and only its `UNIFI_*` keys are used. Load any trusted env file explicitly in the launcher; Docker Compose `env_file:` continues to work.
- API key authentication is supported as an experimental additive option
- The relay sidecar connects to a Cloudflare Worker via token-scoped WebSocket — no inbound ports are exposed

### Site Manager Cloud Credential

The Site Manager server (`apps/sitemanager/`) is not local-first. It has a different trust boundary from the console servers:

- Every request goes to Ubiquiti's cloud at `https://api.ui.com`, including when an MCP client runs the server locally over stdio. The destination is a constant in the code and cannot be changed by environment or configuration. Redirects are never followed and proxy environment variables are ignored.
- TLS uses standard certificate verification against the public CA trust store. There is no verification switch or fingerprint pin to configure, and none is needed.
- Its one credential, a Site Manager API key, reads every console, site and device the UI account can see, from anywhere on the internet. Treat it as more sensitive than any single console's local key.
- The key is read only from `UNIFI_SITEMANAGER_API_KEY` or its `_FILE` / `_COMMAND` form. It is never taken from `UNIFI_API_KEY`, any other shared `UNIFI_*` variable, `config.yaml` or `CONFIG_PATH`, and it is never sent to a console. Console credentials are never sent to the cloud.
- The server is read-only: the Site Manager API has no write operations and the server registers none.
- Over HTTP, anyone who can reach the endpoint can read the whole account's inventory. Keep the default loopback bind and set a bearer token. The Cloud Relay does not include this server unless an operator adds it to `UNIFI_RELAY_SERVERS`; a relay token for that location, including a read-only one, could then read the whole account.
- In `unifi-api-server`, the key is stored encrypted in the API database, is never returned by any route, and is managed only with the `admin` scope. Once it is configured, every API key with the `read` scope can read the whole account.

### InnerSpace Console Session

The InnerSpace server (`apps/innerspace/`) is local-first, but it has its own credential rule:

- It reads and writes InnerSpace on a console with a login session (username and password), never an API key. A console's local `UNIFI_API_KEY` is never read or sent to InnerSpace, and an InnerSpace controller on `unifi-api-server` is refused without a username and password; a stored API token is never passed to its connection.
- The destination is the console you name. Redirects are never followed and proxy environment variables are ignored, so the session cookie cannot be sent elsewhere. Certificate checks follow the same fingerprint and verification settings as the console servers.
- Nine tools read and 15 write the layout. The writes preview first, apply only on `confirm=true`, and honour `UNIFI_INNERSPACE_READ_ONLY` and the `UNIFI_POLICY_INNERSPACE_*` gates. Floor plans describe a building, so the results are sensitive even though response redaction hides secret-looking fields: MAC addresses and plan geometry are not redacted.
- Over HTTP, anyone who can reach the endpoint reads, and with confirmation changes, the project with the server's login. Keep the loopback bind and set a bearer token. The Cloud Relay does not include this server unless an operator adds it to `UNIFI_RELAY_SERVERS`.
- `unifi-api-server` never returns plan image bytes on any surface.

### UniFi Drive NAS Login

The Drive server (`apps/drive/`) is local-first and talks only to the NAS you name:

- A UNAS is its own UniFi OS console, so the server takes its host, port, username and password from `UNIFI_DRIVE_*` only and never sends the gateway's `UNIFI_HOST` login to the NAS, or the NAS login anywhere else. It uses a local UniFi OS account on the NAS (a login session, no API key). A rejected login pauses further logins on an escalating cool-down so repeated tool calls cannot lock the account out.
- Redirects are never followed and proxy environment variables are ignored, so the session cookie cannot be sent elsewhere. Certificate checks are off by default, as for the console servers; pin the NAS certificate with `UNIFI_DRIVE_SSL_FINGERPRINT` (the shared `UNIFI_SSL_FINGERPRINT` is not used for the NAS).
- Writes change who can reach the data, never the data itself: file services (SMB, NFS, Time Machine) and NFS client access. Each previews first and runs on `confirm=true`, one at a time per server process. No tool erases a disk or deletes a pool or shared drive.
- Over HTTP, anyone who can reach the endpoint can use those writes with the server's login. Keep the loopback bind and set a bearer token. The Cloud Relay does not include this server unless an operator adds it to `UNIFI_RELAY_SERVERS`.

### MCP Transport Trust Boundary

- MCP HTTP does not authenticate callers by default. Anyone who can reach it can invoke the enabled tools using the server's controller credentials. Allowed Host/Origin checks protect against DNS rebinding; they do not authenticate a network peer.
- Setting `UNIFI_MCP_HTTP_AUTH_TOKEN` makes HTTP require one static bearer token on every request ([details](apps/network/docs/transports.md#http-bearer-token)). It has no scopes, expiry or per-client revocation, and it is not encryption: carry it only over TLS or loopback. `UNIFI_MCP_HTTP_AUTH_TRUSTED_NETWORKS` exempts the address an authenticating proxy connects from, matched on the TCP peer address; every process that can connect from a listed address is trusted like the proxy. List the proxy's own pinned address: a Docker network's gateway carries host traffic to published ports, and a loopback address covers every local process. `UNIFI_<SERVER>_MCP_HTTP_AUTH_TRUSTED_NETWORKS` replaces the list for one server, and an empty value turns the exemption off there.
- Package defaults disable HTTP and use a loopback bind address when enabled. Docker Compose explicitly enables HTTP inside its container network and publishes ports 3000–3002 on host `127.0.0.1` only. The opt-in `sitemanager` profile adds port 3003, the opt-in `drive` profile port 3004 and the opt-in `innerspace` profile port 3005, also on `127.0.0.1`.
- Remote MCP clients must use the authenticated Cloud Relay gateway, an authenticated TLS reverse proxy, or a TLS tunnel to a backend with the bearer token set. Restrict direct backend access to that proxy; never publish the backend on a LAN/public interface. Trust every process/container with backend access.
- Use Docker Engine 28.0.0 or newer with ordinary NAT bridge networking. Older Docker engines can expose localhost-published ports to peers on the same network; direct-routing, host-network, and custom firewall configurations require separate access restrictions. See [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/).

### Permission System

- **Confirm-by-default** for all mutations (create, update, delete) — the client must explicitly request execution
- **Policy gates** (`UNIFI_POLICY_*` env vars) provide hard boundaries to disable specific actions when needed
- Read-only operations are always allowed
- All tools are always visible and discoverable in the tool index — authorization is enforced at call time
- Tools denied by policy gates return a clear error with guidance on how to enable

### Preview-Before-Confirm

- All state-changing operations use a two-step flow: preview first, then confirm
- Default call returns a preview of what would change
- Explicit `confirm=True` is required to execute the mutation
- By default the server does not verify human approval or require a previous preview. A client can supply `confirm=True` directly. Human approval must be enforced by the MCP client; `confirm` is an execution guard, not caller authentication or a prompt-injection defense.
- `UNIFI_REQUIRE_PREVIEW_TOKEN=true` makes `confirm=True` require a single-use, short-lived token from a preview of the same tool and arguments ([preview tokens](docs/permissions.md#preview-tokens-opt-in)). It proves the previewed request is the one executed, not that a human approved it.
- `UNIFI_TOOL_PERMISSION_MODE=bypass` can bypass this for automation workflows

### No Persistent Storage

- All state lives on the UniFi controller (or, for Site Manager, the UI account) — the MCP server stores nothing locally
- No database, no cache, no session files
- Configuration is read from environment variables and config YAML at startup

## Known Controller Vulnerabilities

These are vulnerabilities in Ubiquiti's UniFi controller software, **not in this MCP server**. They apply to the consoles the Network, Protect, Access, InnerSpace and Drive servers connect to; the Site Manager server talks only to Ubiquiti's cloud API. We document them here so users can verify their controllers are patched.

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

- MCP server code (`apps/network/`, `apps/protect/`, `apps/access/`, `apps/sitemanager/`, `apps/innerspace/`, `apps/drive/`)
- Shared packages (`packages/unifi-core/`, `packages/unifi-mcp-shared/`)
- Relay sidecar (`packages/unifi-mcp-relay/`)
- Cloudflare Worker relay and CLI (`apps/worker/`)
- Claude Code plugins (`plugins/`)

### Out of Scope

The following are **not** maintained by this project. Report issues to their respective maintainers:

- UniFi controller firmware (report to [Ubiquiti](https://community.ui.com))
- Ubiquiti's Site Manager API service at `api.ui.com` (report to [Ubiquiti](https://community.ui.com))
- [aiounifi](https://github.com/Kane610/aiounifi) library
- [pyunifiprotect](https://github.com/uilibs/uiprotect) library
- [py-unifi-access](https://github.com/sirkirby/py-unifi-access) library
- MCP protocol specification (report to [modelcontextprotocol](https://github.com/modelcontextprotocol/specification))
