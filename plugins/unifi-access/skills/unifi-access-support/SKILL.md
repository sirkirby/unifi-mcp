---
name: unifi-access-support
description: >-
  Generate a sanitized UniFi Access support bundle, help the user review it locally,
  and prepare it for a bug report without posting it
---

# Prepare a UniFi Access Support Bundle

Use `access_get_support_bundle` to collect the smallest useful, sanitized support bundle. The server
returns JSON only to the configured MCP client; this skill never posts, uploads, comments,
or opens an issue for the user.

## Choose the Probe

- Start with `summary`. It is local/cache-only and does not contact the controller.
- Use `connectivity` only when connection or authentication behavior is relevant. Explain
  that it makes one bounded read-only request through the existing authenticated session,
  then ask for explicit confirmation before calling it.

If the user asks "show me what will be collected first," explain the selected probe and
the included/excluded data classes before invoking the tool.

## Generate

Call `access_get_support_bundle(probe="summary")` unless the user selected and confirmed another
supported probe. Never route this tool through `*_execute`, `*_batch`, a relay, or a
multi-location fan-out.

If the tool is missing, recommend updating the `access` plugin or package and
restarting the MCP client. If the server cannot start or register tools, use
`$unifi-access-setup` for setup help and fall back to the bug form's manual version,
controller, install, client, expected, actual, and reproduction fields. Do not ask for
credentials, raw configuration, controller payloads, or broad diagnostic logs.

## Review Locally

Show the complete returned JSON to the user and pause before any external sharing. Tell them:

- The bundle is sanitized, not anonymous. Package/controller versions, runtime modes,
  capability flags, and coarse structural shapes can correlate or fingerprint an environment.
- It excludes credentials, controller addresses, identifiers, raw resource values,
  response bodies, raw exception text, logs, configuration files, and caller-supplied
  paths or endpoints.
- `UNIFI_MCP_DIAGNOSTICS` logs are a separate operator facility and are not automatically safe to post publicly.
- They may remove optional sections or values they do not want to share, while keeping
  `schema_version`, `product`, `probe`, and the relevant evidence when possible.

Ask the user to confirm they reviewed the JSON and did not manually add raw logs, payloads,
configuration, credentials, controller identifiers, or security-vulnerability details.

## Prepare for the Bug Report

After review, give the user either:

1. A fenced `json` block they can paste into the **Support bundle (optional)** bug-form field; or
2. A local `.json` file they can inspect before dragging into GitHub.

Dragging a file into GitHub begins publication/upload, and an attachment on a public issue
is publicly accessible. Do not recommend screenshots of JSON. This support skill must never
upload, attach, paste, post, or submit the bundle. Return only the reviewed JSON or its local
path; any publication must happen outside this support workflow.

Canonical guide: https://github.com/sirkirby/unifi-mcp/blob/main/docs/support-bundles.md
