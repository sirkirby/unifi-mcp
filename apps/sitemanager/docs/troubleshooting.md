# Troubleshooting — Site Manager Server

This server has no support-bundle tool. To report a problem, see [Reporting a problem](#reporting-a-problem).

## Setup and startup

### The server lists only `sitemanager_setup_status`

No API key is set. Set `UNIFI_SITEMANAGER_API_KEY` (or its `_FILE` / `_COMMAND` form) and restart the server. `UNIFI_API_KEY` is not used: it holds a console's local key.

After changing the key or any setting:

1. Restart the server. For a stdio server, that means restarting the client or starting a new session, since the client launches it.
2. Confirm the variable reaches the server's process. A variable exported in your shell does not reach a server launched by a desktop client; put it in the client's server entry or in the file named by `UNIFI_SETTINGS_FILE`.
3. Call `sitemanager_setup_status` again if it is still listed. It reports what is missing without making any request.

### The server exits at startup with a `[credentials]` error

The key provider could not be resolved, and the server refuses to start rather than run without it (exit code 6). The log line names the variable and the reason:

- **More than one spelling set.** Keep exactly one of `UNIFI_SITEMANAGER_API_KEY`, `_FILE` and `_COMMAND`.
- **The file does not exist, is not a regular file, or cannot be read.** Check the path from the server's point of view, including inside a container.
- **The command was not found or failed.** Give its absolute path or a name on `PATH`. It must print the key and exit within 30 seconds.
- **The value is empty or has more than one line.** The file or command output must hold the key on one line.

An HTTP auth token variable that is set but empty, too short or malformed also refuses startup. See [configuration.md](configuration.md#http-transport).

This is different from setup mode: with no key at all the server starts and lists `sitemanager_setup_status`.

## Key and account

### "rejected the API key" (401)

The key is wrong, revoked or expired, or it is a console's local key rather than a Site Manager key. Create a new one at unifi.ui.com > Settings > API Keys.

### "refused this request" (403)

The key lacks the Site Manager scope, or the account cannot read that resource.

### A host or site is missing

The API returns what the key's account can see: consoles it owns or has been invited to. A key created inside a Fabric lists only that Fabric's consoles.

### "not found" for a host or SD-WAN configuration

The id is not one the account can see, or it is not a Site Manager id. Take host ids from `sitemanager_list_hosts` and configuration ids from `sitemanager_list_sdwan_configs`.

### An id from this server fails in another server

Site Manager ids are their own family. A host, site or device id from these tools is not valid in the Network, Protect or Access servers.

## Results

### A list returns fewer entries than expected

List tools return one page. Pass `next_cursor` back as `cursor` until it is `null`. A page can be short or empty while more pages remain.

### ISP metrics are empty for a site

Not every site reports ISP metrics. The query tool returns no series for such a site and does not set `partial`. `5m` metrics are kept for 24 hours and `1h` metrics for 30 days.

### ISP metrics show a summary but few or no periods

That is `period_limit`: each site returns its 12 most recent periods by default, and none with `period_limit: 0`. The summary always covers the whole window. Raise `period_limit` (up to 720) for more of the series.

### The ISP metrics query returns `partial` with no series

The account cannot read some or all of the sites in the query, or their ids are wrong. Check the `host_id` and `site_id` values against `sitemanager_list_sites`.

### SD-WAN returns an empty list

The account has no SD-WAN configurations. This is a normal result, not an error.

### Rate limited (429)

The API allows 10,000 requests per minute. The server waits out a short limit on a read, up to about ten seconds in one call. Beyond that it returns the time to wait.

## Network

### Timeouts and connection errors

The server needs outbound HTTPS (port 443) to `api.ui.com`, and DNS that resolves it. It ignores proxy environment variables, so it cannot reach the API through a proxy that must be configured that way. Raise `UNIFI_SITEMANAGER_TIMEOUT_SECONDS` if responses are slow.

There is no console to reach, so the local-network checks in the other servers' guides (console address, port, firewall between you and the console) do not apply.

### "unexpected redirect"

Something between the server and `api.ui.com` answered with a redirect, such as a captive portal or an intercepting proxy. The server does not follow redirects, so the key is never sent to wherever it points. Fix the network path.

### Certificate errors

`api.ui.com` uses a publicly trusted certificate, and the server always verifies it. There is no setting to turn verification off or to pin a certificate. A certificate error usually means a TLS-inspecting proxy or firewall is intercepting the connection; exempt `api.ui.com` from inspection.

## Missing tools

### A tool is not in the client's tool list

1. If only `sitemanager_setup_status` is listed, no key is set (see above).
2. In `meta_only` mode the nine tools are not listed; reach them through `sitemanager_execute`, or switch to the default `lazy` mode.
3. In `eager` mode, `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS` may be filtering them out.
4. Some clients cache the tool list. Start a new session after changing the registration mode.

`sitemanager_tool_index` lists every tool the server has, with `category`, `search` and `include_schemas` filters. See [tools.md](tools.md#meta-tools).

### The client asks for approval for `sitemanager_execute`, or refuses it

`sitemanager_execute` and `sitemanager_batch` are not marked read-only, because a dispatcher cannot promise what it will run. Call the tool by name instead; all nine are listed directly in the default lazy mode and are marked read-only. See [permissions.md](permissions.md#meta-tools-and-read-only-clients).

### No tools visible at all

1. Check the server's stderr log: did it start, or exit with a `[credentials]` error?
2. Confirm the client shows the server as connected.
3. Start a new client session so it lists tools again.

## Docker

The image and Compose service are built from a checkout until the first release; see the [README](../README.md#docker-compose).

### The container exits immediately

Read `docker logs unifi-sitemanager-mcp`. A `[credentials]` error means the key provider could not be resolved (see [above](#the-server-exits-at-startup-with-a-credentials-error)). Inside a container, a `_FILE` path must point to a secret mounted into the container, and a `_COMMAND` helper must be installed in the image. With no key at all the container keeps running in setup mode.

### Cannot reach the API from the container

The container needs outbound HTTPS to `api.ui.com`. Check that the Docker network allows egress and that DNS works inside the container.

### Setting the key for Docker

The only credentials the Compose service takes from your shell are `UNIFI_SITEMANAGER_API_KEY`, `UNIFI_SITEMANAGER_API_KEY_FILE` or `UNIFI_SITEMANAGER_API_KEY_COMMAND`, and the HTTP auth token variables. It does not read the shared `.env` file, and console variables such as `UNIFI_API_KEY` never reach it.

```bash
export UNIFI_SITEMANAGER_API_KEY="$(cat "$HOME/.config/unifi-mcp/sitemanager-api-key")"
docker compose -f docker/docker-compose.yml --profile sitemanager up --build unifi-sitemanager-mcp
```

### Cannot connect to port 3003

The service is published on `127.0.0.1:3003` only, so it is reachable from the Docker host, not from other machines. If a request is refused with a Host header error, add the host name you use to `UNIFI_MCP_ALLOWED_HOSTS`.

## Debug logging

```bash
export UNIFI_MCP_LOG_LEVEL=DEBUG
export UNIFI_MCP_DIAGNOSTICS=true
```

Logs go to stderr; stdout is reserved for MCP messages in stdio mode. Diagnostics add one line per tool call with its name, duration and outcome, never its arguments or result.

The API key and request headers are never logged. Request failures and rate-limit waits are logged with the request path, which can contain a host or SD-WAN configuration id. Remove those before sharing a log.

## Reporting a problem

Errors include a trace id from Ubiquiti when one was returned. Include it in a bug report, along with the tool name, the error text and the server version. Do not include your API key, host ids, site names, MAC addresses or IP addresses.
