# Troubleshooting

## Generate a reviewed support bundle first

If the server starts, run `access_get_support_bundle(probe="summary")` and review the JSON locally before sharing it. Use `probe="connectivity"` only after agreeing to one bounded read-only controller request. See the canonical [support bundle guide](../../../docs/support-bundles.md) for the privacy boundary, direct and marketplace flows, and pre-start fallback. Ordinary `UNIFI_MCP_DIAGNOSTICS` logs are not automatically safe to post publicly.

## Connection Issues

### Cannot connect to controller

**Symptoms:** Connection timeout, refused, or "cannot reach host" errors.

**Check:**
1. Verify the controller is reachable: `curl -k https://<UNIFI_HOST>:<UNIFI_PORT>`
2. Confirm `UNIFI_ACCESS_HOST` and `UNIFI_ACCESS_PORT` are correct
3. If using Docker, ensure the container can reach the controller (use `--network host` or the correct Docker network)
4. Check firewall rules between the MCP server and the controller

### Authentication failures (proxy session)

**Symptoms:** 401 Unauthorized on port 443, "invalid credentials" errors.

**Check:**
1. Verify `UNIFI_ACCESS_USERNAME` and `UNIFI_ACCESS_PASSWORD` are correct
2. Ensure the account is a **local admin** (not a Ubiquiti SSO account)
3. Try logging into the UniFi OS Console web UI with the same credentials
4. Confirm the Access application is installed and running on the controller

### API key auth failing (port 12445)

**Symptoms:** 401 on port 12445, `py-unifi-access` connection errors.

**Check:**
1. Verify `UNIFI_ACCESS_API_KEY` is correct and has not been revoked
2. Confirm port 12445 is reachable from the MCP server: `curl -k https://<HOST>:12445`
3. Check that the Access application exposes port 12445 (some network configurations or Docker setups may block non-standard ports)
4. The API key is generated from the UniFi OS Console under Settings > API Keys

### Proxy session fallback

**Symptoms:** Some tools work but others return "proxy session required" errors.

**Explanation:** Credential management, policies, and other proxy-backed mutations require the local session (port 443 with username/password). Visitor operations are different: list/get/create/delete use the Access Developer API and require `UNIFI_ACCESS_API_KEY` on port 12445.

**Fix:** Configure both `UNIFI_ACCESS_USERNAME`/`UNIFI_ACCESS_PASSWORD` and `UNIFI_ACCESS_API_KEY` for full functionality. For visitor-only failures, verify the Access API token and port 12445 first.

### "Access application not found" errors

**Symptoms:** Connection succeeds but the server reports Access is not available.

**Check:**
1. Log into the UniFi OS Console and verify the Access application is installed
2. Ensure the Access application is running (not stopped or updating)
3. Check that your admin account has access to the Access application

## SSL Issues

### SSL certificate verification errors

**Symptoms:** `SSL: CERTIFICATE_VERIFY_FAILED` or similar errors.

**Fix:** Set `UNIFI_ACCESS_VERIFY_SSL=false` (most UniFi controllers use self-signed certificates).

```bash
export UNIFI_ACCESS_VERIFY_SSL=false
```

This is the default, so this error typically only occurs if you explicitly set it to `true`.

## Missing Tools

### Tool not appearing in client tool list

Policy gates do not hide tools. In `lazy` mode, domain tools are discovered
through `access_tool_index` and called through `access_execute`; they are not all
registered directly with the client at startup. In `meta_only` mode, the index
initially contains only meta-tools, and `access_execute` can run a domain tool
when its name is already known. That execution lazily registers the tool's
module, so later client lists and index results can include its domain tools.

**Fix:**
1. Use the default `lazy` mode with `access_tool_index` for discovery
2. Use `access_execute` to call the tool, or set `UNIFI_TOOL_REGISTRATION_MODE=eager` to register all tools directly
3. In `eager` mode, check whether `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS` is limiting registration

### Tool returns "permission denied" via access_execute

**Cause:** A policy gate is denying the action at call time. Policy checks run
before preview/confirmation, so `confirm=true` does not bypass a denied policy.

**Fix:** Check [permissions.md](permissions.md) for the relevant category, set the
current policy variable named in the error, and restart the server.

**Example:** To allow Access door updates:
```bash
export UNIFI_POLICY_ACCESS_DOORS_UPDATE=true
```

### No tools visible at all

**Check:**
1. Verify the server started successfully (check stderr logs)
2. Confirm your MCP client is connected
3. Try `UNIFI_TOOL_REGISTRATION_MODE=eager` to load all tools immediately
4. Check if `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS` is set and limiting the tools

## Event Streaming Issues

### No real-time events in buffer

**Symptoms:** `access_recent_events` returns empty results; `access://events/stream` resource is empty.

**Check:**
1. Verify `ACCESS_WEBSOCKET_ENABLED=true` (default)
2. Check server logs for websocket connection errors
3. Ensure `UNIFI_ACCESS_API_KEY` is configured (websocket events may require API key auth)
4. Verify Access devices are generating events (try unlocking a door manually)
5. Use `access_list_events` to verify events exist on the controller (REST API works independently)

### Events disappearing from buffer

**Cause:** Buffer overflow or TTL expiration.

**Fix:**
- Increase `ACCESS_EVENT_BUFFER_SIZE` (default 100) for high-traffic environments
- Increase `ACCESS_EVENT_BUFFER_TTL` (default 300 seconds) if you poll less frequently
- Poll more frequently (every 2-5 seconds) to process events before they expire

## Docker Issues

### Container exits immediately

**Check:**
1. Ensure `-i` flag is set (stdin must be open for stdio transport)
2. Check logs: `docker logs <container>`
3. Verify all required env vars are set (`UNIFI_ACCESS_HOST` plus credentials)

### Cannot connect to controller from Docker

**Fix options:**
1. Use `--network host` to share the host network stack
2. Or ensure the Docker network can route to the controller IP
3. Verify the controller IP is not a localhost address (use the actual network IP)
4. For API key auth, ensure port 12445 is accessible from the container (not just port 443)

### Environment variable setup for Docker

```bash
docker run -i --rm \
  -e UNIFI_ACCESS_HOST=192.168.1.1 \
  -e UNIFI_ACCESS_USERNAME=admin \
  -e UNIFI_ACCESS_PASSWORD=your-password \
  -e UNIFI_ACCESS_API_KEY=your-api-key \
  -e UNIFI_POLICY_ACCESS_DOORS_UPDATE=true \
  ghcr.io/sirkirby/unifi-access-mcp:latest
```

Or use an env file:
```bash
docker run -i --rm --env-file .env ghcr.io/sirkirby/unifi-access-mcp:latest
```

## Debug Logging

Enable verbose logging to diagnose issues:

```bash
export UNIFI_MCP_LOG_LEVEL=DEBUG
export UNIFI_MCP_DIAGNOSTICS=true
```

This outputs detailed information about:
- Access connection and dual-path authentication
- WebSocket connection state
- Permission decisions
- Tool registration
- API requests and responses (redacted)
- Tool call timing

All logs go to stderr (stdout is reserved for MCP JSON-RPC in stdio mode).
