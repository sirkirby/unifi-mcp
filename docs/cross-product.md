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
Cloudflare Worker. The worker provides `unifi_location_timeline` when a relay is
connected: it collects bounded Network and Protect evidence through the same
product evidence tools available to local clients, which the relay forwards.
See the [incident evidence contract](incident-evidence.md#relay-and-worker-consumers).

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
3. **Mappings.** A camera is tied to the device only by an exact identifier. When
   the client lists the read-only lookups `protect_get_camera` and
   `unifi_get_client_details` directly (lazy mode does from
   `unifi-network-mcp` 0.38.1 and `unifi-protect-mcp` 0.9.1, the servers the
   Network and Protect plugins pin), the skill runs
   them itself to show the camera's MAC as a Network client on that device; it
   asks the user only when the lookups are unavailable or show no such
   relationship. A described camera is used only once the user gives its ID. Similar names and
   nearby timestamps never create a mapping. The mapping is passed to both tools
   as `mappings` assertions; ambiguous or missing mappings are reported and the
   camera is left out.
4. **Collection.** One call per evidence tool with the same window and explicit
   `max_window_seconds`, `max_events`, `max_calls`, `max_elapsed_ms` and
   `max_records_returned`. Each returns a bounded client view that fits in one
   tool result. A spent budget, timeout or truncation is reported, with a
   bounded follow-up offered only when it would change coverage; unknown
   truncation and records omitted from the view always get a "split the window"
   offer.
5. **Report.** Incident and inputs; coverage per source (outcome, queried window,
   filters, pagination, truncation, retention, budgets, failures) and the
   records returned and omitted; every record in the view cited by its full
   evidence ID in one fixed format; hypotheses labelled as correlation;
   source-backed identity only; unanswered questions and next reads. An empty
   source always carries the caveat that controller retention is unknown.

If only Network is connected, the skill stops, reports Protect unavailable and,
with the user's consent, runs a Network-only investigation labelled as having no
camera context. Worked reports built from the golden evidence corpus are in
`plugins/unifi-intelligence/skills/incident-investigation/references/report-examples.md`.
The evidence contract, budgets and the checks a consumer applies are in
[Incident evidence](incident-evidence.md).

## The Location Timeline Tool

`unifi_location_timeline` combines one versioned incident evidence document per
product and location, and by default returns its
[client view](incident-evidence.md#client-view): per-source coverage and
failures, mappings, budgets and a bounded list of record citations, with omitted
records counted. `detail: "full"` returns the whole combined document.

Parameters:

- `start` / `end` (required): a half-open ISO 8601 window with explicit UTC offsets.
- `location_id`: select one relay location; omitted, the worker queries all registered locations. A call reads at most 7 sources (locations × products, with one Protect source per camera ID), and a larger selection is refused before any read.
- `products`: Network and Protect by default; Access is explicitly unsupported if requested.
- `device_macs` / `camera_ids`: exact identifiers, never inferred from names.
- `mappings`: explicit exact-identifier assertions from the operator or product inventory.
- `max_window_seconds`, `max_events`, `max_calls`, `max_elapsed_ms`: limits passed to each product collection.
- `detail`: `view` (default) or `full`; `max_records_returned`: citations in the view, 1 to 50, default 25; `resume_after`: the view's `record_selection.next_cursor`, to read the records after it.

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
remain in the evidence. All sources failing yields `overall: "failed"`;
incomplete evidence cannot establish an all-clear. Source-ID disagreements fail
combination; select one location when controllers return conflicting source IDs.
The former `start_time`/`end_time`, `area_hint` and `event_types` parameters are no
longer supported.

## UniFi Intelligence Skills

The `unifi-intelligence` plugin ships three cross-product skills:

| Skill | Use Case | Products |
|-------|----------|----------|
| **Security Patrol** | "What happened at the front entrance?" | Network + Protect through the cloud worker; Access read separately |
| **Incident Investigation** | "A switch went offline — what happened?" | Network + Protect, local |
| **Visitor Audit** | "Which access and network activity was observed today?" | Access read separately + Network through the cloud worker |

The plugin is listed in the Claude Code and Codex marketplaces and ships skills
only, no MCP server. It requires the `unifi-network` and `unifi-protect`
plugins: Claude Code installs them as its dependencies, while Codex and OpenClaw
install no plugin dependencies, so install and set up those two first there (see
the [install guide](agent-install.md#unifi-intelligence)). The skills can also be
installed as [standalone skills](agent-install.md#standalone-skills-through-npm)
from `plugins/unifi-intelligence`. Each skill declares required and optional
servers in its Dependencies section.

Incident Investigation requires the local Network and Protect servers and uses
their incident evidence tools; it needs neither the cloud worker nor the relay.
Security Patrol and Visitor Audit need the cloud worker: they call
`unifi_location_timeline`, which the cloud worker provides through a connected
relay. The timeline covers Network and Protect and reports Access as
unsupported, so both skills read door events separately with
`access_list_events` and report that read's coverage apart from the
timeline's. Both turn an area or door into exact device MACs and camera IDs
before calling the timeline, which never matches names. Visitor Audit also
requires Access; Security Patrol needs at least one product (two for a
multi-product correlation). Without the cloud worker, those two stop with no
tool call, stating that no merged timeline is available; they may offer local
reads in words and make none until the user agrees. Every read they make uses a
tool the client lists directly as read-only, never `*_execute` or `*_batch`.

Reports include Coverage and Limitations: requested interval, source availability,
filters, returned counts, caps and failures. A sorted timeline does not establish
complete coverage. Missing, partial or capped evidence cannot support an all-clear.
Timing alone establishes neither a person's identity, device ownership nor cause;
reports separate observations from hypotheses and source-backed account attribution.
