# Local plugins and trustworthy incident investigation

Status: proposed design; [tracking issue #787](https://github.com/sirkirby/unifi-mcp/issues/787).
This document defines the target behavior and contributor boundaries, not a claim
that installation or incident acceptance has passed.

## Goal and scope

Make UniFi plugins dependable in local Claude Code and Codex, then support one
bounded, read-only investigation of a Network device incident with Protect camera
context. Users should understand what was observed, where it came from, and what
could not be checked. Local controllers and explicit credentials remain the
starting point; a relay must never be an undeclared prerequisite.

The first slice takes an incident/device and an explicit time window, verifies
available sources and device/camera mappings, collects bounded evidence, and
returns a cited timeline with observations, hypotheses and unanswered questions.
Access and broader cross-product workflows can reuse the contract later.

## Responsibilities

| Layer | Responsibility |
| --- | --- |
| Core | Versioned evidence models, product normalization, mapping validation, bounded collection/correlation policy and product managers. Build on `unifi_core.event_timeline`; controller access remains behind ConnectionManagers. No MCP or app imports. |
| MCP | Thin argument validation, discovery metadata and response formatting around Core; preserve standard success/error envelopes and read-only annotations. |
| API | Thin adapters to the same Core behavior and evidence. Preserve provenance, coverage and errors through REST/GraphQL serialization; avoid a second correlation implementation. |
| Canonical skill | Gather incident inputs, check prerequisites, request bounded evidence and explain it without overstating identity, causality or completeness. |
| Plugin | Package the skill, client-specific manifests, dependencies, safe setup and supported-version information. Installation is an independently tested product boundary. |
| Relay/worker | Optional transport/aggregation consumers of the same schema and golden fixtures; no independent evidence semantics. TypeScript consumers validate the contract without importing Python. |

Follow the existing [architecture](ARCHITECTURE.md) and [repository rules](../AGENTS.md).
Product API families have distinct auth and ID spaces; adapters must use their
actual tool signatures and payloads. Never turn a public UUID into a legacy ID by
assumption or let thin wrappers own controller/business logic.

## Evidence guarantees

The shared contract must retain:

- **Provenance:** product, controller/site or location scope, API/tool family,
  source record ID, query parameters and collection time. Reports cite evidence
  records; secrets are excluded and existing egress redaction remains in force.
- **Time:** requested interval, original timestamp, normalized UTC timestamp,
  timezone/precision and known clock uncertainty. Missing or invalid time is
  explicit; collection time never substitutes silently for event time.
- **Mapping:** device/camera/location IDs, mapping source and confidence or
  ambiguity. Similar names and nearby timestamps do not establish a mapping,
  personal identity or causality.
- **Coverage:** requested and observed source/window coverage, applied filters,
  pagination, caps, truncation and malformed/dropped records. A retrieved count
  is not the total population unless completeness is established.
- **Failure:** distinguish an empty successful query from an unavailable source,
  denied permission, timeout, parse failure and partial response. Partial evidence
  retains per-source status; total failure cannot become a successful empty
  timeline. Incomplete evidence never justifies an unconditional all-clear.

Collection has explicit time-window, event, call and elapsed-time budgets.
Budget exhaustion returns visible partial coverage. Reports separate observations
from hypotheses and explain missing evidence before suggesting further reads.
No mutation is part of investigation acceptance.

## Plugin compatibility and setup

Maintain a matrix of supported client versions, OS/shell, Python/uv, plugin and
package versions, transport and required product/relay connections. Label each
cell tested, unsupported or not tested; static consistency is not host evidence.

Use current [OpenAI packaging rules](https://developers.openai.com/plugins/build/plugins)
for portable root `plugin.json` and `mcp.json`, including supported legacy
`.codex-plugin/plugin.json` fallback, and the separate
[Claude manifest reference](https://code.claude.com/docs/en/plugins-reference).
Do not infer incompatibility from a legacy layout alone. Verify marketplace
resolution and installed behavior for the exact supported clients.

Setup must validate before replacing configuration, preserve unrelated values and
working registration on failure, and handle credential providers and variable
precedence consistently across shell and PowerShell. Credentials must not appear
in chat, command arguments or acceptance artifacts.

## Dependency order and acceptance gates

| Phase | Work | Exit evidence |
| --- | --- | --- |
| A: Plugin health | [Packaging/matrix #788](https://github.com/sirkirby/unifi-mcp/issues/788), [safe setup #789](https://github.com/sirkirby/unifi-mcp/issues/789), [skills/docs #790](https://github.com/sirkirby/unifi-mcp/issues/790), then [host acceptance #791](https://github.com/sirkirby/unifi-mcp/issues/791) | Clean marketplace install, skill/tool discovery, MCP initialize/tools/list, harmless authenticated reads and upgrade preservation in both local clients; exact versions and sanitized evidence. |
| B: Trustworthy investigation | [Core/adapters #792](https://github.com/sirkirby/unifi-mcp/issues/792), then [bounded slice #793](https://github.com/sirkirby/unifi-mcp/issues/793), then [acceptance/readiness #794](https://github.com/sirkirby/unifi-mcp/issues/794) | Shared golden fixtures across consumers, equivalent MCP/API evidence and canonical-skill reports in both clients, plus a bounded live Network+Protect read against an identified installable artifact. |

Core evidence design and fixtures may proceed alongside Phase A. Feature release
requires **both Gate A and Gate B**. The common corpus covers complete, empty,
partial, failed, truncated and ambiguously mapped evidence, plus timezone and
schema drift cases. Test actual manifest signatures rather than mocks that
repeat the implementation's assumptions.

Acceptance records identify client/OS/controller and package versions, artifact
origin, supported matrix cells and unresolved blockers. Verify installed module
paths to rule out workspace substitution. Keep issues open while required
installation, released-artifact or live verification remains; merging code alone
is insufficient. No dates or staffing commitments are implied.

## Non-goals

This design does not add remediation, mutations, continuous monitoring, alerting,
a controller replacement, persistent evidence storage, personal identification,
or a broad multi-product feature suite. Hosted ChatGPT distribution is a separate
future decision with its own [submission requirements](https://developers.openai.com/plugins/guides/submit-claude-plugin).
Local client acceptance does not establish hosted eligibility.

The tracking issues hold audit motivation and execution evidence. Recheck current
source before implementation and reuse independently completed maintenance work;
do not duplicate fixes based on the original audit snapshot.
