# Troubleshooting

## Generate a reviewed support bundle first

If the server starts, run `unifi_get_support_bundle(probe="summary")` and review the JSON locally before sharing it. Use `probe="connectivity"` only after agreeing to one bounded read-only controller request. See the canonical [support bundle guide](../../../docs/support-bundles.md) for the privacy boundary, direct and marketplace flows, and pre-start fallback. Ordinary `UNIFI_MCP_DIAGNOSTICS` logs are not automatically safe to post publicly.

## Connection Issues

### Cannot connect to controller

**Symptoms:** Connection timeout, refused, or "cannot reach host" errors.

**Check:**
1. Verify the controller is reachable: `curl -k https://<UNIFI_HOST>:<UNIFI_PORT>`
2. Confirm `UNIFI_HOST` and `UNIFI_PORT` are correct
3. If using Docker, ensure the container can reach the controller (use `--network host` or the correct Docker network)
4. Check firewall rules between the MCP server and the controller

### Authentication failures

**Symptoms:** 401 Unauthorized, "invalid credentials" errors.

**Check:**
1. Verify `UNIFI_USERNAME` and `UNIFI_PASSWORD` are correct
2. Ensure the account is a **local admin** (not a Ubiquiti SSO account)
3. Try logging into the controller web UI with the same credentials
4. If using an API key: note that API key auth is experimental and limited to read-only operations — username/password are still required for full functionality

### SSO/MFA auth fails but tools say "Not connected"

If logs show `SSO MFA required but no totp_secret configured`, the controller is reachable but the configured account requires an MFA flow that Network MCP does not currently expose in configuration. Configure a dedicated local UniFi admin/service account without SSO MFA or local 2FA, then restart the MCP client so the updated environment is loaded.

### 404 errors on API calls

**Symptoms:** Tools return 404 Not Found or "endpoint not found" errors.

**Cause:** Wrong API path structure for your controller type.

**Fix:**
1. Try setting `UNIFI_CONTROLLER_TYPE=proxy` (for UniFi OS / UDM-Pro / Cloud Gateway)
2. Or `UNIFI_CONTROLLER_TYPE=direct` (for standalone controllers)
3. If `auto` detection fails, manual override eliminates the guessing

## SSL Issues

### SSL certificate verification errors

**Symptoms:** `SSL: CERTIFICATE_VERIFY_FAILED` or similar errors.

**Fix:** Set `UNIFI_VERIFY_SSL=false` (most UniFi controllers use self-signed certificates).

```bash
export UNIFI_VERIFY_SSL=false
```

This is the default, so this error typically only occurs if you explicitly set it to `true`.

## Missing Tools

### Tool not appearing in client tool list

Policy gates do not hide tools. In `lazy` mode, domain tools are discovered
through `unifi_tool_index` and called through `unifi_execute`; they are not all
registered directly with the client at startup. In `meta_only` mode, the index
initially contains only meta-tools, and `unifi_execute` can run a domain tool
when its name is already known. That execution lazily registers the tool's
module, so later client lists and index results can include its domain tools.

**Fix:**
1. Use the default `lazy` mode with `unifi_tool_index` for discovery
2. Use `unifi_execute` to call the tool, or set `UNIFI_TOOL_REGISTRATION_MODE=eager` to register all tools directly
3. In `eager` mode, check whether `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS` is limiting registration

### Tool returns "permission denied" via unifi_execute

**Cause:** A policy gate is denying the action at call time. Policy checks run
before preview/confirmation, so `confirm=true` does not bypass a denied policy.

**Fix:** Check [permissions.md](permissions.md) for the relevant category and set
the exact policy variable named in the error, then restart the server so it
inherits the updated environment.

**Example:** To allow Network creation tools when the Networks category gate is
denying the call:
```bash
export UNIFI_POLICY_NETWORK_NETWORKS_CREATE=true
```

### Policy variable set but the action is still denied

**Cause:** The variable name does not match a gate this server registers, so it
is never read. Category names in `UNIFI_POLICY_NETWORK_<CATEGORY>_<ACTION>`
are the config keys listed in [permissions.md](permissions.md), which differ from
the `permission_category` shorthand in `tools_manifest.json`.

**Fix:** At startup the server logs every unrecognized `UNIFI_POLICY_*` variable
with the closest valid names:
```
[policy] Unrecognized env var UNIFI_POLICY_NETWORK_CLIENT_GROUP_DELETE: no gate in the network tool manifest matches it. Did you mean UNIFI_POLICY_NETWORK_CLIENT_GROUPS_DELETE, ...?
```
Rename the variable to the suggested name and restart the server. The same applies
in the deny direction: a misnamed variable set to `false` blocks nothing.

### No tools visible at all

**Check:**
1. Verify the server started successfully (check stderr logs)
2. Confirm your MCP client is connected
3. Try `UNIFI_TOOL_REGISTRATION_MODE=eager` to load all tools immediately
4. Check if `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS` is set and limiting the tools

## HTTP Transport Issues

### HTTP endpoint not starting

**Check:**
1. Verify `UNIFI_MCP_HTTP_ENABLED=true` is set
2. If not running as PID 1 (non-container), set `UNIFI_MCP_HTTP_FORCE=true`
3. Check that the port is not already in use

### Host validation errors behind reverse proxy

**Symptoms:** 403 Forbidden or "host not allowed" errors.

**Fix:**
```bash
export UNIFI_MCP_ALLOWED_HOSTS=localhost,127.0.0.1,your-domain.com
```

If that does not resolve it:
```bash
export UNIFI_MCP_ENABLE_DNS_REBINDING_PROTECTION=false
```

## Docker Issues

### Container exits immediately

**Check:**
1. Ensure `-i` flag is set (stdin must be open for stdio transport)
2. Check logs: `docker logs <container>`
3. Verify all required env vars are set (`UNIFI_HOST`, `UNIFI_USERNAME`, `UNIFI_PASSWORD`)

### "ModuleNotFoundError" in Docker

**Cause:** Usually a build issue.

**Fix:** Pull the latest image:
```bash
docker pull ghcr.io/sirkirby/unifi-network-mcp:latest
```

## Debug Logging

Enable verbose logging to diagnose issues:

```bash
export UNIFI_MCP_LOG_LEVEL=DEBUG
export UNIFI_MCP_DIAGNOSTICS=true
```

This outputs detailed information about:
- Controller type detection
- Permission decisions
- Tool registration
- API requests and responses (redacted)
- Tool call timing

All logs go to stderr (stdout is reserved for MCP JSON-RPC in stdio mode).
