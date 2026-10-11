# Cross-Product Capabilities

An MCP client connected to multiple UniFi product servers can query Network, Protect, and Access in a single session. This page explains how to use cross-product features.

## How It Works

Each UniFi product (Network, Protect, Access) runs as an independent MCP server. When connected to the same MCP client or relay, an agent can call tools from all three in one conversation.

### Local Mode (stdio)

Each server runs independently. An agent connected to all three can call tools from each, but cross-product correlation must be done by the agent itself — calling individual event-listing tools and reasoning across the results.

### Relay Mode (recommended for cross-product)

The [relay sidecar](../packages/unifi-mcp-relay/) connects all local servers to a Cloudflare Worker. In relay mode, the `unifi_location_timeline` tool is available — it queries events across all connected products and returns a unified, time-sorted timeline.

## The Location Timeline Tool

`unifi_location_timeline` merges events from Network, Protect, and Access into a single stream.

**Parameters:**
- `start_time` / `end_time` (required) — ISO 8601 time window
- `location_id` (optional) — filter to a specific location (relay mode only, queries all locations if omitted)
- `products` (optional) — filter to specific products (defaults to all connected)
- `area_hint` (optional) — filter by area name (e.g., "front door" matches AP, camera, and door names)
- `event_types` (optional) — filter by event type

**Example:**
> "Show me everything that happened at the front entrance between 2 AM and 3 AM"

The agent calls `unifi_location_timeline(start_time="2026-03-24T02:00:00Z", end_time="2026-03-24T03:00:00Z", area_hint="front entrance")` and gets back Network client connections, Protect camera motion events, and Access badge scans — all in one sorted timeline.

## Hero Skills

Three repository skills describe cross-product workflows:

| Skill | Use Case | Products |
|-------|----------|----------|
| **Security Patrol** | "What happened at the front entrance?" | Network + Protect + Access |
| **Incident Investigation** | "A switch went offline — what happened?" | Network + Protect |
| **Visitor Audit** | "Which access and network activity was observed today?" | Access + Network |

These skills live in `plugins/cross-product/skills/`; they are not automatically
installed by the individual product plugins. Availability depends on the client
and its installed skill packages; verify discovery before invoking them. Each
skill declares required and optional servers in its Dependencies section.

All three merged-timeline workflows require the relay's `unifi_location_timeline`
tool. Incident Investigation also requires Network; Visitor Audit requires Access
and optionally Network; Security Patrol needs at least one product (two for a
multi-product correlation). Without the relay, stop the merged workflow and offer
separate local reads, explicitly stating that no merged timeline is available.

Reports include Coverage and Limitations: requested interval, source availability,
filters, returned counts, caps and failures. A sorted timeline does not establish
complete coverage. Missing, partial or capped evidence cannot support an all-clear.
Timing alone establishes neither a person's identity, device ownership nor cause;
reports separate observations from hypotheses and source-backed account attribution.
