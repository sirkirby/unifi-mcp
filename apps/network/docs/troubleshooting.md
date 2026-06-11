# Troubleshooting

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

**Cause:** The tool's permission is disabled.

**Fix:**
1. Check [permissions.md](permissions.md) for the relevant category
2. Enable via environment variable:
   ```bash
   export UNIFI_PERMISSIONS_<CATEGORY>_<ACTION>=true
   ```
3. Restart the server

**Example:** If `unifi_create_network` is missing:
```bash
export UNIFI_PERMISSIONS_NETWORKS_CREATE=true
```

### Tool returns "permission denied" via unifi_execute

**Cause:** In lazy/meta_only mode, `unifi_tool_index` shows all tools (from the static manifest), but disabled tools return permission errors when called.

**Fix:** Same as above — enable the permission and restart.

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
