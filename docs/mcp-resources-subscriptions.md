# MCP Resources and Subscriptions Alignment

This note maps UniFi MCP event and snapshot surfaces to the MCP 2025-11-25
resource model. It keeps the existing REST/API SSE endpoints in place for
non-MCP API clients and treats MCP resources as an MCP-native context surface,
not as a replacement transport.

Reference: https://modelcontextprotocol.io/specification/2025-11-25/server/resources

## Current Resource Inventory

| Server | URI | Type | Contents | Update mode |
| --- | --- | --- | --- | --- |
| Protect | `protect://events/stream` | Resource | Recent websocket event buffer as JSON | Poll |
| Protect | `protect://events/stream/summary` | Resource | Event count summary as JSON | Poll |
| Protect | `protect://cameras/snapshots` | Resource | Camera snapshot URI index as JSON | Poll |
| Protect | `protect://cameras/{camera_id}/snapshot` | Resource template | Live JPEG snapshot bytes | On demand |
| Access | `access://events/stream` | Resource | Recent event buffer as JSON | Poll |
| Access | `access://events/stream/summary` | Resource | Event count summary as JSON | Poll |

These resources now expose MCP-native metadata:

- `title` for UI display.
- `annotations` for host-side prioritization.
- Namespaced `_meta` keys describing UniFi-specific behavior:
  - `io.unifi.resourceKind`
  - `io.unifi.updateMode`
  - `io.unifi.pollIntervalMs` where polling is expected
  - `io.unifi.protocolSubscribe`
  - `io.unifi.relatedTools`

## Resource Candidates

| Candidate | Recommendation | Rationale |
| --- | --- | --- |
| Recent events | Keep as resources | Event buffers are bounded, contextual snapshots that fit `resources/read`. |
| Event buffer summaries | Keep as resources | Summaries are lightweight and useful for automatic context selection. |
| Camera snapshot index | Keep as resource | It is a discoverable index of available snapshot resource URIs. |
| Individual camera snapshots | Keep as resource template | The URI template maps directly to MCP resource templates and returns binary content. |
| Door status snapshots | Add later as Access resource templates | `access://doors/{door_id}/status` would fit once we want a reference beyond events. |
| Device status snapshots | Add later as Network or Access resource templates | Useful for status context, but should be scoped per product and tested separately. |

## Subscriptions

MCP defines `resources/subscribe` and
`notifications/resources/updated` for resource update pushes. The current MCP
SDK exposes low-level request handlers and `ServerSession.send_resource_updated`,
but FastMCP does not expose a public broadcast API that can safely emit resource
notifications from UniFi websocket callbacks running outside a request session.

Because of that, UniFi MCP should not advertise protocol resource subscriptions
yet. The resource `_meta` value `io.unifi.protocolSubscribe: false` is
intentional. Clients should poll the resource URIs or use the existing
`*_subscribe_events` tools for instructions until a safe notification path
exists.

Adoption gate before enabling `resources/subscribe`:

1. FastMCP exposes a supported server/session notification broadcast API, or we
   add a well-tested local session registry without patching SDK internals.
2. Event managers can emit `notifications/resources/updated` for the exact URI
   whose backing buffer changed.
3. Tests cover subscribe, unsubscribe, update notification delivery, and
   shutdown cleanup.
4. Relay behavior is verified so remote clients receive the same update
   semantics as local clients.

## API SSE Separation

The API server SSE endpoints under `apps/api/src/unifi_api/routes/streams/`
remain separate and in scope for non-MCP API users. They should not be removed
or redirected as part of MCP resource alignment. MCP resources are optimized for
host-driven context selection; API SSE streams are optimized for application
clients that need long-lived event streams.

## Reference Implementation

The current reference implementation is the Protect and Access event resource
metadata pattern:

- Existing URIs remain stable.
- Resource reads continue returning the same JSON payloads.
- MCP metadata tells clients how to display and refresh resources.
- Protocol subscriptions are explicitly marked unavailable until update
  notifications can be delivered correctly.
