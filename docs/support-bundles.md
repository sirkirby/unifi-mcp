# Support Bundles

Use a support bundle when a UniFi Network, Protect, or Access MCP server starts but behaves unexpectedly. It gathers a small, structured set of troubleshooting facts without collecting raw controller responses or ordinary diagnostic logs.

The shortest path is:

1. Generate a `summary` with the matching product support skill or MCP tool.
2. Review the returned JSON locally.
3. Paste the reviewed JSON into the bug form, or save and inspect it before attaching the `.json` file.

Support bundles are sanitized, not anonymous. Versions, runtime modes, capability flags, and coarse structural shapes can still correlate or fingerprint an environment.

## Marketplace flow

Use the product-qualified skill installed with the matching plugin:

```text
$unifi-network-support Show me what will be collected first, then prepare a Network support bundle.
$unifi-protect-support Show me what will be collected first, then prepare a Protect support bundle.
$unifi-access-support Show me what will be collected first, then prepare an Access support bundle.
```

The skill explains the selected probe before collection, generates the JSON, and pauses for your review. It does not post, upload, attach, or open an issue.

## Direct MCP flow

Start with the local/cache-only `summary` probe:

```text
unifi_get_support_bundle(probe="summary")
protect_get_support_bundle(probe="summary")
access_get_support_bundle(probe="summary")
```

If a connection or authentication failure is relevant, explicitly confirm that you want the one-shot `connectivity` probe before calling it:

```text
unifi_get_support_bundle(probe="connectivity")
protect_get_support_bundle(probe="connectivity")
access_get_support_bundle(probe="connectivity")
```

Connectivity performs one bounded read-only request through the product server's existing authenticated session. It has a 10-second request timeout, does not retry, reconnect, reauthenticate, refresh bootstrap state, or start websocket work, and returns only a fixed outcome plus a duration bucket. Only one live probe runs at a time, and the same probe has a 30-second cooldown.

Protect also defines this currently unsupported call:

```text
protect_get_support_bundle(probe="resource_shape", resource="sensors")
```

This invocation documents the contract, not an available diagnostic: in the current version it returns `unsupported` because the installed Protect client and available reference controller did not expose a verified UP-AirQuality sensor shape. Do not request or call it in this release; use `summary` for environment evidence instead. Do not claim issue #523 coverage. Network and Access resource-shape probes are also unsupported. Ask before running a `connectivity` probe.

Support tools are intentionally unavailable through every cloud relay path. Generate the bundle against the direct Network, Protect, or Access MCP server. Do not route it through `*_execute`, `*_batch`, or a multi-location fan-out.

## What the bundle includes

The closed, versioned JSON schema can include:

- support schema and sanitizer policy versions;
- product package, Python, and selected dependency versions;
- operating-system family and architecture enums;
- configured transport, content, and tool-registration modes;
- generated manifest tool count and fixed feature flags;
- normalized connection state, TLS-verification state, last-attempt category, and remediation code;
- controller application and UniFi OS versions when already available in trusted memory;
- fixed product capability flags, such as whether an authenticated session or API key path is configured;
- for connectivity, a fixed outcome and coarse duration bucket;
- sanitizer bounds and suppression/truncation indicators.

The entire successful response envelope is valid JSON and limited to 32 KiB. Structural traversal, where supported, is limited to 100 items, 16 variants, depth 6, 64 fields per object, and 2,000 nodes.

## What it excludes

A support bundle does not include:

- credentials, cookies, API keys, tokens, passwords, or raw authentication headers;
- controller addresses, IP or MAC addresses, hostnames, URLs, serial numbers, UUIDs, site IDs, usernames, email addresses, or user-assigned names;
- SSIDs, door or camera names, event media, images, recordings, or raw resource scalar values;
- raw controller request or response bodies;
- raw exception text, tracebacks, application logs, shell history, MCP transcripts, crash dumps, or configuration files;
- arbitrary caller-supplied endpoints, paths, filenames, environment names, tools, or queries;
- hashes, encodings, pseudonyms, or correlation tokens derived from suppressed identifiers.

Turning ordinary response redaction off does not change this boundary. The support-bundle sanitizer is independent and always enforced.

## Support bundles versus diagnostic logs

`UNIFI_MCP_DIAGNOSTICS` is an operator-oriented logging facility. It can preserve operational identifiers such as controller hosts and uses broader fallback serialization. Those logs are not automatically safe to post publicly, even when response redaction is enabled.

Prefer a support bundle first. Share raw tool output or diagnostics only when a maintainer specifically asks for it and only after manual sanitization.

## Review before sharing

Inspect the complete JSON locally. You may remove optional sections or values you do not want to publish. When possible, keep `schema_version`, the product/tool identity, the selected `probe`, and the evidence relevant to the report.

Before submitting, confirm:

- the product and probe match the report;
- you did not manually add raw payloads, logs, configuration, credentials, or controller identifiers;
- the bundle does not contain security-vulnerability details;
- you understand that the remaining version and capability metadata may fingerprint or correlate your environment.

For a suspected vulnerability, stop and use [GitHub Security Advisories](https://github.com/sirkirby/unifi-mcp/security/advisories) instead of a public issue.

## Paste or attach

The recommended option is to paste the reviewed JSON into the bug form's **Support bundle (optional)** field as a fenced block:

````text
```json
{
  "success": true,
  "data": {
    "server": {
      "schema_version": 1
    }
  }
}
```
````

This lets bounded automated triage recognize the supplied evidence. Do not use a screenshot of JSON.

Alternatively, save the response as a `.json` file and inspect the local file before dragging it into GitHub. Dragging a file into GitHub begins publication/upload. An attachment on a public issue is publicly accessible. Automated triage treats an attachment only as an indication that a file was supplied; it does not open, download, or inspect the attachment.

Automated triage publishes fixed trusted text for label suggestions and relationship assessments, including workflow summaries. Free-form rationale text is validated as input but is never published. Requests for support evidence come only from the allowlisted request renderer, not from those rationales.

## If the tool is missing or the server cannot start

If the support tool is missing:

1. Update the matching plugin or MCP package.
2. Restart the MCP client so its tool catalog refreshes.
3. Use `$unifi-network-setup`, `$unifi-protect-setup`, or `$unifi-access-setup` for product setup help.

A support bundle cannot diagnose a failure that prevents the server from starting or registering tools. In that case, use the bug form's existing manual version, controller, install method, MCP client, operating system, expected/actual behavior, and reproduction fields. Do not post credentials, raw configuration, or unsanitized logs.

The MCP host, model provider, transcript retention, and any later GitHub publication are outside the server-enforced boundary. The server performs no secondary upload, callback, paste creation, telemetry submission, or issue comment; it returns JSON only through the configured MCP transport.

## Repeatable acceptance checks

From the repository root, run `uv run --all-packages python scripts/live_smoke.py --server all --phase support`.
Selecting this phase explicitly authorizes the bounded, read-only connectivity probes. It starts real stdio
servers in lazy, eager, and meta-only modes and checks discovery, summary/connectivity schemas, the 32 KiB
envelope limit, configured identity/secret canaries (raw, SHA256, base64), cooldown, invalid-input rejection,
and sanitizer independence from ordinary response redaction. It never runs mutations or collects resource shapes.
Reports contain only product/mode, pass/fail, and byte counts; bundles and subprocess logs are not saved.
Failure stops the matrix without retrying authentication.

For installed-wheel verification, use an isolated Python environment with the app wheels installed and invoke
`uv run --no-project --python /path/to/venv/bin/python scripts/live_smoke.py --server all --phase support`.
This uses that interpreter's installed app entrypoints, not workspace imports.

After release/version sync, add `--support-plugin-root /path/to/fresh/marketplace-checkout` to validate the
packaged support skills, both host manifests, and matching package pins, then launch the actual `.mcp.json`
commands through `uvx` with a fresh temporary cache. The returned bundle version must match the plugin pin.
This verifies the packaged skill/tool pair; separately check skill discovery in the MCP host after install/upgrade.
Unit coverage is in `tests/test_live_smoke_harness.py`. The broader readonly/preview/disposable-resource and API
release matrix remains a separate gate; ordinary `--phase safe` alone does not prove support acceptance.

## Maintainer request examples

Ask for the smallest probe that can answer the open question:

```text
Please run unifi_get_support_bundle with probe="summary", review the JSON locally, and paste the reviewed result in the Support bundle field. Guide: https://github.com/sirkirby/unifi-mcp/blob/main/docs/support-bundles.md
```

```text
Please run protect_get_support_bundle with probe="connectivity" only if you agree to one bounded controller request, review the JSON locally, and paste the reviewed result. Guide: https://github.com/sirkirby/unifi-mcp/blob/main/docs/support-bundles.md
```
