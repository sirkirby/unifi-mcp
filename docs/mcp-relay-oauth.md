# MCP Relay OAuth Boundary

This decision record defines where MCP OAuth belongs in UniFi MCP. The short
version: OAuth is a relay/cloud concern only. Local Network, Protect, and Access
servers stay local-first and continue to use environment/config credentials.

References:

- [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [MCP security best practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
- [MCP transports specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

## Decision

Do not add OAuth to local stdio-only UniFi MCP servers.

If UniFi MCP adopts MCP OAuth, the adoption boundary is the cloud relay path:

```text
Cloud MCP client
    |
    | MCP over HTTPS
    v
Cloudflare Worker relay gateway
    |
    | authenticated WebSocket
    v
unifi-mcp-relay sidecar
    |
    | MCP over HTTP on the user's LAN
    v
Local Network, Protect, and Access MCP servers
```

The Worker is the only component that can plausibly act as an MCP protected
resource for external clients. The relay sidecar remains a local connector that
authenticates to the Worker. The product servers remain local servers that
authenticate to UniFi controllers through local config.

This decision is intentionally additive:

- Existing local stdio/env-var authentication remains supported.
- Existing relay `AGENT_TOKEN`, `ADMIN_TOKEN`, and per-location relay-token
  flows remain supported.
- OAuth, if implemented, must be optional until a separate breaking-change
  issue defines migration notes and a compatibility window.

## Why Not Local OAuth

The MCP authorization spec says authorization is optional, HTTP transports
should follow the OAuth profile when authorization is supported, and stdio
transports should retrieve credentials from the environment instead.

That matches UniFi MCP's local deployment model:

- Local app servers are intended to run beside the MCP client or on the user's
  LAN.
- They access local UniFi controllers, not a hosted multi-tenant UniFi MCP
  service.
- The sensitive credentials are controller credentials or local API keys, which
  already come from config/env and should not leave the local deployment.
- Adding OAuth to stdio-only app servers would add complexity without improving
  the local trust boundary.

## Current Relay Auth Model

The current cloud relay path uses three token classes:

| Token | Used by | Route | Purpose |
| --- | --- | --- | --- |
| `AGENT_TOKEN` | Cloud MCP clients | `POST /mcp` | Protects the public MCP endpoint. |
| `ADMIN_TOKEN` | Worker CLI/admin API | `/api/*` | Creates and manages relay locations. |
| Per-location relay token | `unifi-mcp-relay` sidecar | `GET /ws` WebSocket upgrade | Authenticates one local relay location. |

The sidecar sends the relay token as an `Authorization: Bearer` header on the
WebSocket connection. The Worker stores relay tokens as hashes and uses
constant-time token comparison for direct bearer-token checks.

This is not MCP OAuth. It is a simple deployment mode for self-hosted relay
users. It should remain the default until OAuth has a concrete interoperability
need and a tested migration path.

## OAuth Adoption Shape

If OAuth becomes warranted for the relay, the Worker should implement it as an
MCP resource server in front of `/mcp`.

Minimum standard-aligned shape:

1. Serve OAuth protected resource metadata for the public MCP resource.
2. Return `401` responses with a `WWW-Authenticate` challenge that includes a
   resource metadata URL and, when useful, a scope challenge.
3. Validate bearer access tokens issued for the Worker MCP resource.
4. Validate token audience/resource binding so tokens issued for other resources
   are rejected.
5. Use standard `Authorization: Bearer <token>` headers on every HTTP request.
6. Map insufficient-scope failures to `403` and invalid/expired tokens to
   `401`.

The Worker should not try to become a general-purpose authorization server.
Prefer an external authorization server or identity provider, with the Worker
acting as a resource server that validates tokens and advertises metadata.

## Scope Model

OAuth scopes should describe relay-level authority, not UniFi controller
credentials. A first-pass scope model could be:

| Scope | Grants |
| --- | --- |
| `unifi:tools:read` | `initialize`, `tools/list`, read-only relay meta-tools. |
| `unifi:tools:call` | Tool calls routed through the relay. |
| `unifi:locations:read` | Location inventory and status. |
| `unifi:locations:admin` | Location token creation or rotation. |

Mutation safety still belongs to the existing UniFi permission system. OAuth
scopes do not replace preview-then-confirm, policy gates, or per-tool
annotations.

## Relay Sidecar Boundary

OAuth does not need to cross the sidecar boundary at first.

The sidecar's job is to keep a persistent, authenticated connection to the
Worker and forward MCP calls to local servers. Per-location relay tokens remain
the right primitive for that machine-to-machine leg because they are scoped to
one location, can be rotated independently, and do not require local browser
flows.

If OAuth is later required for sidecar registration, it should be designed as a
separate machine-token exchange and must not require local Network, Protect, or
Access servers to understand OAuth.

## Adoption Triggers

Do not implement relay OAuth merely to look more standard. Implement it when at
least one of these becomes true:

- A target cloud MCP client requires MCP OAuth discovery and rejects pre-shared
  bearer tokens.
- UniFi MCP offers a hosted or shared Worker deployment where multiple users or
  organizations need delegated access.
- Admin operations need per-user identity, revocation, or consent beyond a
  single `ADMIN_TOKEN`.
- The MCP ecosystem converges on protected resource metadata as the expected
  way for public HTTP MCP servers to advertise auth.

Until then, the current token model is acceptable for self-hosted relay
deployments.

## Implementation Guardrails

Any future OAuth implementation must preserve these compatibility rules:

- No OAuth requirement for local stdio app servers.
- No OAuth requirement for local MCP HTTP servers used by the sidecar.
- No removal of `AGENT_TOKEN`, `ADMIN_TOKEN`, or per-location relay tokens
  without a separate breaking-change issue.
- No migration that exposes UniFi controller credentials to the Worker or any
  external authorization server.
- No token forwarding from cloud clients to local app servers.
- Protocol smoke tests must cover both token-auth and OAuth-enabled Worker
  modes before OAuth becomes generally available.

## Follow-Up Position

No implementation issue is required yet. OAuth is warranted only when one of the
adoption triggers above is concrete. The next relay-auth implementation issue
should be opened with a specific client, deployment, or identity-provider target
so scope design and migration risk are testable.
