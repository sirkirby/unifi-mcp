# Cross-Product Capabilities

An MCP client connected to multiple UniFi product servers can query Network, Protect, and Access in a single session. This page explains how to use cross-product features.

## How It Works

Each UniFi product (Network, Protect, Access) runs as an independent MCP server. When connected to the same MCP client or relay, an agent can call tools from all three in one conversation.

### Local Mode (stdio)

Each server runs independently. An agent connected to several servers can call
tools from each and correlate the results itself. Network and Protect each expose
a read-only incident evidence tool that returns cited records with per-source
coverage, so a local client can investigate an incident without the relay (see
[Incident Investigation](#incident-investigation)).

### Relay Mode

The [relay sidecar](../packages/unifi-mcp-relay/) connects local servers to a
Cloudflare Worker. Its `unifi_location_timeline` consumer collects bounded
Network and Protect evidence through the same product evidence tools available
to local clients. See the [incident evidence contract](incident-evidence.md).

## Incident Investigation

The Incident Investigation skill investigates one Network device incident, with
Protect camera context, over an explicit window. It needs only the local Network
and Protect servers; the relay is not used.

1. **Inputs.** The user confirms the device's exact MAC, a window with a date and
   timezone, the cameras to include and the budgets, before anything is read.
2. **Tools.** The client must list `unifi_get_incident_evidence` and
   `protect_get_incident_evidence` with `readOnlyHint: true`. The default lazy
   registration mode lists both directly, so a client restricted to read-only
   tools can call them; `meta_only` mode does not list them.
3. **Mappings.** A camera is tied to the device only by an exact identifier: the
   user states it, or read-only lookups show the camera's MAC as a Network client
   on that device. Similar names and nearby timestamps never create a mapping. The
   mapping is passed to both tools as `mappings` assertions; ambiguous or missing
   mappings are reported and the camera is left out.
4. **Collection.** One call per evidence tool with the same window and explicit
   `max_window_seconds`, `max_events`, `max_calls` and `max_elapsed_ms`. A spent
   budget, timeout or truncation is reported, with a bounded follow-up offered
   only when it would change coverage.
5. **Report.** Incident and inputs; coverage per source (outcome, queried window,
   filters, pagination, truncation, budgets, failures); cited observations;
   hypotheses labelled as correlation; source-backed identity only; unanswered
   questions and next reads.

If only Network is connected, the skill stops, reports Protect unavailable and,
with the user's consent, runs a Network-only investigation labelled as having no
camera context. Worked reports built from the golden evidence corpus are in
`plugins/cross-product/skills/incident-investigation/references/report-examples.md`.
The evidence contract, budgets and the checks a consumer applies are in
[Incident evidence](incident-evidence.md).

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

Incident Investigation requires the local Network and Protect servers and uses
their incident evidence tools; the relay is optional and unused. Security Patrol
and Visitor Audit are merged-timeline workflows that require the relay's
`unifi_location_timeline` tool. Visitor Audit also requires Access and optionally
Network; Security Patrol needs at least one product (two for a multi-product
correlation). Without the relay, those two stop the merged workflow and offer
separate local reads, explicitly stating that no merged timeline is available.

Reports include Coverage and Limitations: requested interval, source availability,
filters, returned counts, caps and failures. A sorted timeline does not establish
complete coverage. Missing, partial or capped evidence cannot support an all-clear.
Timing alone establishes neither a person's identity, device ownership nor cause;
reports separate observations from hypotheses and source-backed account attribution.
