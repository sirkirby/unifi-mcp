# Cross-Product Capabilities

UniFi MCP is the only tool that lets AI agents query Network, Protect, and Access in a single session. This page explains how to use cross-product features.

## How It Works

Each UniFi product (Network, Protect, Access) runs as an independent MCP server. When connected to the same MCP client or relay, an agent can call tools from all three in one conversation.

### Local Mode (stdio)

Each server runs independently. An agent connected to all three can call tools from each, but cross-product correlation must be done by the agent itself — calling individual event-listing tools and reasoning across the results.

### Relay Mode

The [relay sidecar](../packages/unifi-mcp-relay/) connects local servers to a
Cloudflare Worker. Its `unifi_location_timeline` consumer collects bounded
Network and Protect evidence through the same product evidence tools available
to local clients. See the [incident evidence contract](incident-evidence.md).

## The Location Timeline Tool

`unifi_location_timeline` returns one versioned incident evidence document with
ordered records, provenance, mappings, per-source coverage and failures.

Parameters:

- `start` / `end` (required): a half-open ISO 8601 window with explicit UTC offsets.
- `location_id`: select one relay location; omitted, the worker queries all registered locations.
- `products`: Network and Protect by default; Access is explicitly unsupported if requested.
- `device_macs` / `camera_ids`: exact identifiers, never inferred from names.
- `mappings`: explicit exact-identifier assertions from the operator or product inventory.
- `max_window_seconds`, `max_events`, `max_calls`, `max_elapsed_ms`: limits passed to each product collection.

For example, after obtaining the exact device and camera identifiers, call:

```json
{
  "start": "2026-08-08T12:00:00Z",
  "end": "2026-08-08T13:00:00Z",
  "device_macs": ["02:00:00:00:00:01"],
  "camera_ids": ["fixture-camera"],
  "max_events": 200,
  "max_calls": 10
}
```

Inspect `data.overall`, `data.coverage_complete`, `data.sources` and
`data.budgets.exhausted` before assessing the incident. Failed and missing sources
remain in the evidence document. All sources failing yields `overall: "failed"`;
incomplete evidence cannot establish an all-clear. Source-ID disagreements fail
combination; select one location when controllers return conflicting source IDs.
The former `start_time`/`end_time`, `area_hint` and `event_types` parameters are no
longer supported.

## Hero Skills

Three built-in skills showcase cross-product capabilities:

| Skill | Use Case | Products |
|-------|----------|----------|
| **Security Patrol** | "What happened at the front entrance?" | Network + Protect + Access |
| **Incident Investigation** | "A switch went offline — what happened?" | Network + Protect |
| **Visitor Audit** | "Who visited today and what devices did they bring?" | Access + Network |

These skills are installed with the `cross-product` plugin.
