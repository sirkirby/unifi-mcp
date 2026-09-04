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
3. Try logging into the Protect web UI with the same credentials
4. The `uiprotect` library requires local authentication -- cloud-only accounts will not work

### "ProtectApiError" or unexpected API responses

**Symptoms:** Tools return errors mentioning `uiprotect` or `ProtectApiError`.

**Check:**
1. Ensure the controller is running UniFi OS with Protect application installed
2. Verify the Protect application is running (not stopped or updating)
3. Check that the user account has access to the Protect application
4. Ensure the NVR firmware is reasonably current (uiprotect targets recent firmware versions)

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
through `protect_tool_index` and called through `protect_execute`; they are not
all registered directly with the client at startup. In `meta_only` mode, the
index contains only meta-tools, and `protect_execute` can run a domain tool when
its name is already known.

**Fix:**
1. Use the default `lazy` mode with `protect_tool_index` for discovery
2. Use `protect_execute` to call the tool, or set `UNIFI_TOOL_REGISTRATION_MODE=eager` to register all tools directly
3. Check whether `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS` is limiting registration

### Tool returns "permission denied" via protect_execute

**Cause:** A policy gate is denying the action at call time. Policy checks run
before preview/confirmation, so `confirm=true` does not bypass a denied policy.

**Fix:** Check [permissions.md](permissions.md) for the relevant category, set the
current policy variable named in the error, and restart the server.

**Example:** To allow Protect camera updates:
```bash
export UNIFI_POLICY_PROTECT_CAMERAS_UPDATE=true
```

### No tools visible at all

**Check:**
1. Verify the server started successfully (check stderr logs)
2. Confirm your MCP client is connected
3. Try `UNIFI_TOOL_REGISTRATION_MODE=eager` to load all tools immediately
4. Check if `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS` is set and limiting the tools

## Event Streaming Issues

### No real-time events in buffer

**Symptoms:** `protect_recent_events` returns empty results; `protect://events/stream` resource is empty.

**Check:**
1. Verify `PROTECT_WEBSOCKET_ENABLED=true` (default)
2. Check server logs for websocket connection errors
3. Ensure the NVR has cameras generating events (try triggering motion manually)
4. Use `protect_list_events` to verify events exist on the NVR (REST API works independently)

### Events disappearing from buffer

**Cause:** Buffer overflow or TTL expiration.

**Fix:**
- Increase `PROTECT_EVENT_BUFFER_SIZE` (default 100) for high-traffic environments
- Increase `PROTECT_EVENT_BUFFER_TTL` (default 300 seconds) if you poll less frequently
- Poll more frequently (every 2-5 seconds) to process events before they expire

### Smart detections missing

**Cause:** Minimum confidence filter is too high.

**Fix:** Lower `PROTECT_SMART_DETECTION_MIN_CONFIDENCE` (default 50):
```bash
export PROTECT_SMART_DETECTION_MIN_CONFIDENCE=25
```

Or pass `min_confidence` parameter directly to `protect_list_smart_detections` or `protect_recent_events`.

## Snapshot Issues

### Snapshot returns error or empty data

**Check:**
1. Verify the camera is connected and online (`protect_list_cameras`)
2. Ensure the camera supports snapshots (most do, but some may be in a degraded state)
3. Try fetching via the tool (`protect_get_snapshot`) with `include_image=true`
4. Check server logs for specific error messages

## HTTP Transport Issues

### HTTP endpoint not starting

**Check:**
1. Verify `UNIFI_MCP_HTTP_ENABLED=true` is set
2. If not running as PID 1 (non-container), set `UNIFI_MCP_HTTP_FORCE=true`
3. Check that port 3001 is not already in use (or change `UNIFI_MCP_PORT`)

## Docker Issues

### Container exits immediately

**Check:**
1. Ensure `-i` flag is set (stdin must be open for stdio transport)
2. Check logs: `docker logs <container>`
3. Verify all required env vars are set (`UNIFI_HOST`, `UNIFI_USERNAME`, `UNIFI_PASSWORD`)

### Cannot connect to NVR from Docker

**Fix options:**
1. Use `--network host` to share the host network stack
2. Or ensure the Docker network can route to the NVR IP
3. Verify the NVR IP is not a localhost address (use the actual network IP)

### "ModuleNotFoundError" in Docker

**Cause:** Usually a build issue.

**Fix:** Pull the latest image:
```bash
docker pull ghcr.io/sirkirby/unifi-protect-mcp:latest
```

## Debug Logging

Enable verbose logging to diagnose issues:

```bash
export UNIFI_MCP_LOG_LEVEL=DEBUG
export UNIFI_MCP_DIAGNOSTICS=true
```

This outputs detailed information about:
- Protect connection and authentication
- WebSocket connection state
- Permission decisions
- Tool registration
- API requests and responses (redacted)
- Tool call timing

All logs go to stderr (stdout is reserved for MCP JSON-RPC in stdio mode).
