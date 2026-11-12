# Permission System — Site Manager Server

Every tool on this server is read-only. The Site Manager API has no write operations, so there is nothing to confirm and nothing to gate.

- **Permission mode** (`UNIFI_TOOL_PERMISSION_MODE`) has no effect here: it governs mutations.
- **Policy gates** (`UNIFI_POLICY_*`) apply to `CREATE`, `UPDATE` and `DELETE` actions. This server has none.
- Every tool is annotated `readOnlyHint: true`, so clients that restrict themselves to read-only tools can call all of them.

## What controls access instead

The API key. A Site Manager key can read every console the account can see, and the server returns whatever the key allows. To narrow what the server can read, narrow the account or the key at [unifi.ui.com](https://unifi.ui.com).

To limit which tools are registered, use eager mode with `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS`. See [configuration.md](configuration.md).

## Response redaction

Responses pass through the same redaction as the other servers. Fields whose names mark them as secrets are replaced with `***REDACTED***` unless `UNIFI_SITEMANAGER_REDACT_SENSITIVE_FIELDS=false`. Independently of that setting, the account holder's name, email and role are never returned.
