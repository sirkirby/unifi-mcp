# Troubleshooting — InnerSpace Server

This server has no support-bundle tool. To report a problem, see [Reporting a problem](#reporting-a-problem).

## Setup and startup

### The server lists only `innerspace_setup_status`

No console host is set, so the server is in setup mode. Set `UNIFI_INNERSPACE_HOST` (or `UNIFI_HOST`), the username and the password, and restart the server. Setup mode makes no request to the console.

After changing a setting:

1. Restart the server. For a stdio server, that means restarting the client or starting a new session, since the client launches it.
2. Confirm the variable reaches the server's process. A variable exported in your shell does not reach a server launched by a desktop client; put it in the client's server entry or in the file named by `UNIFI_SETTINGS_FILE`.
3. Call `innerspace_setup_status` again if it is still listed. It reports what is missing without making any request.

### The server exits at startup

- **Exit code 2 and a log line naming `UNIFI_SSL_FINGERPRINT` or `UNIFI_INNERSPACE_SSL_FINGERPRINT`.** The certificate pin is malformed. It must be a SHA-256 fingerprint. The log does not repeat the value.
- **Exit code 2 and a log line saying the host and port must name a valid console address.** Check `UNIFI_INNERSPACE_HOST` and `UNIFI_INNERSPACE_PORT`: the host is an address or name, without a scheme or path.
- **A `[credentials]` error.** A `_FILE` or `_COMMAND` credential could not be resolved, or more than one spelling of the same credential is set. Keep exactly one. A `_FILE` path must exist, be a regular file and be readable from the server's point of view, including inside a container.
- **An HTTP auth token that is set but empty, shorter than 32 characters or malformed.** See [configuration.md](configuration.md#http-transport).

### The console is down at startup

The server still starts and serves. Each tool call returns fixed text (for example that it is still connecting, or that it could not log in to the console) until the console answers. The next call after that logs in once and succeeds; you do not need to restart the server.

## Console login and access

### "the console refused the session for InnerSpace"

The full text is: "the console refused the session for InnerSpace (expired session or an account without InnerSpace access). Reads need a UniFi OS account that can open the InnerSpace application, e.g. a Super Admin." The console returns the same 403 for an expired session and for an account that cannot open InnerSpace, and gives no separate code, so the server cannot tell them apart.

The server logs in again once and retries. If the fresh session is refused too, the account has no InnerSpace access. Use a UniFi OS account that can open the InnerSpace application in the console UI. For about a minute afterwards, further refusals return the same error without another login. Over the API this is a `403`, not a missing application.

### "the console account cannot read the application list"

UniFi OS answers its system status (`/api/system`) for an expired session with a public reply that has no application list, so the server treats that reply as a refused session: it logs in again once and reads the status again. This error means the fresh session got no list either, so the account cannot see the console's applications. Use a UniFi OS account that can open the InnerSpace application, e.g. a Super Admin. For about a minute afterwards the same reply returns this error without another login. Over the API this is a `403`, not a missing application.

### "rejected the configured username and password" or "must all be configured"

The login was refused, or no username or password reached the server. Look for `UNIFI_PASSWORD is set but not used` (or `UNIFI_USERNAME`) in the login error a tool call returns or in the startup log. The shared credentials go only to the `UNIFI_HOST` console, so when `UNIFI_INNERSPACE_HOST` names another console (an IP address and a hostname for one console count as different) or `UNIFI_HOST` is unset, set `UNIFI_INNERSPACE_USERNAME` and `UNIFI_INNERSPACE_PASSWORD`.

Otherwise check the username and password, and that the account is a local UniFi OS account rather than a Ubiquiti SSO account without a local password. After a rejected login, automatic reconnects pause on an increasing delay (starting at one minute, up to 15 minutes) so repeated calls cannot lock the account out. Fix the credentials and restart the server to retry at once.

### "rate-limited the login"

The console rate-limited the login. The server backs off automatically; wait and call again. A UniFi OS console accepts only a limited number of logins in a short time (in testing, about 20 within a few minutes), and every server start, reconnect and `unifi-api-server` admin probe of the controller spends one, so avoid restarting in a loop while it is limited.

### "Could not log in to the UniFi OS console"

The host and port are not reachable from the machine running the server, or they do not point at the console. Check `UNIFI_INNERSPACE_HOST` and `UNIFI_INNERSPACE_PORT` (default `443`) and any firewall between you and the console. The server ignores proxy environment variables and never follows redirects, so it cannot reach a console through a proxy that must be configured that way.

## InnerSpace itself

### "InnerSpace is not installed on this console" versus "not running"

These are two different results, and each comes from the console's system endpoint, never from a 403 or a 404:

- **Not installed.** The console lists no InnerSpace application. Install it from the console's application list. Over the API this is a `502`, not a `404`.
- **Not running.** InnerSpace is installed but stopped. Start it in the console's application list. `innerspace_get_status` also shows an installed version and any update.

The server does not probe for InnerSpace at startup. Whether it is installed and running is decided at the first read, and the answer is cached for about 30 seconds, so a freshly started application can take that long to be seen.

### "no such floor plan"

The `plan_id` is not one in this project. Take plan ids from `innerspace_list_floor_plans` or `innerspace_get_project`. They are InnerSpace ids: an id from the Network, Protect, Access or Site Manager server is not valid here.

### "invalid arguments"

An argument failed validation: an id that is not a single plain path segment, an extra argument, a `limit` outside 1-2000, or a `unit` other than `metric` or `imperial`. The server's own validation never repeats the rejected value. An argument of the wrong type, such as text for `limit`, is rejected earlier by the MCP framework, whose error to the caller quotes the value it was sent; the server's log names only the argument.

### A list is shorter than expected

`innerspace_list_walls` and `innerspace_list_placed_devices` cut the list at `limit` (default 500). Check `truncated` and `total` and raise `limit`, up to 2000.

### Positions are `null` and `scale_missing` is true

The plan has no usable scale, so lengths cannot be converted. Set the scale on the plan in InnerSpace.

### Positions do not line up with the plan image

Positions are in the plan's own coordinate frame, measured from the plan's top-left in the project's unit. They match image pixels directly only when `image_scale` is `1` and `image_offset` is `(0, 0)`. Otherwise convert with the formulas in [tools.md](tools.md#coordinates-and-the-plan-image): you need the plan's `scale_per_unit`, `width_px`, `height_px`, `image_scale` and `image_offset`, all returned with the plan.

### The image is refused

The plan image resources refuse an image above 8,000,000 bytes, and one that is not an image of the type the plan's address promises, with fixed text. Each resource serves one type: a JPEG plan read through `innerspace://plans/{plan_id}/image` is refused with text naming `innerspace://plans/{plan_id}/image.jpg`, and the other way round. Use the `resource_uri` that `innerspace_get_plan_asset` returns. Over `unifi-api-server` no image is served at all.

## Writes

### "InnerSpace is not installed" or "not running"

Every write and its preview read the app list first and stop here, before anything is sent. Check the app with `innerspace_get_status` and start it in UniFi OS.

### "an object created by an identical earlier call was changed"

Ids for new objects follow from the arguments. An earlier identical call created them, and since then one has changed, or some are gone while others remain, so the call is refused rather than sent. Change an argument, or remove the existing object first. If all of them are gone, the call is not refused: it creates them again under the same ids.

### "is disabled by policy" or "is in read-only mode"

A `UNIFI_POLICY_INNERSPACE_*` gate set to `false`, or `UNIFI_INNERSPACE_READ_ONLY` (or `UNIFI_READ_ONLY`), blocks the tool, its preview included. The message names the variable to change. See [permissions.md](permissions.md).

### "item N is not a wall on this plan now"

Between the preview and the confirm the object was removed, moved to another plan or changed type, for example in the browser editor. Nothing was sent. Read the plan again and repeat the call with current ids.

### Frame coordinates are refused

The plan's image is shifted or scaled, the plan has no usable scale or image size, or the position is outside the image. Pass `coordinates: "plan_units"` with the console's own values, or change only fields without positions.

### `success: false` with `mutation_applied: false`

The console refused the write (an HTTP 4xx, or UniFi OS refusing it again on a fresh session) and the read-back shows no change; nothing was applied. The `error` says what the console answered. The same call can be sent again once the cause is fixed.

### "time budget ran out before the change was sent"

A confirmed write holds the console's write turn for at most `UNIFI_INNERSPACE_WRITE_HOLD_SECONDS`. When that runs out before the write goes out, during the fresh reads or just before the send, nothing is sent and the result is `mutation_applied: false`. Read the plan again and retry; raise the hold budget if a slow console keeps hitting it. When it runs out after the write was sent, the outcome is unknown (`mutation_applied: null`), below.

### "The innerspace controller is busy" on a confirmed write

Another write still held the console's write turn after this call had waited `UNIFI_INNERSPACE_CALL_WAIT_SECONDS`, or had held it past its hold budget, so nothing was sent and the MCP result is `mutation_applied: false` (over the API, a `503`). Retry shortly, or send the change through `innerspace_batch`, which waits its turn.

### `success: false` with `mutation_applied: null`

The answer was lost, the console's answer was not a refusal (a 5xx, 429 or an unreadable answer) and the read-back did not show every change after a few re-reads, or the read-back shows only part of the change; an edit made at the same time, from another server process or the InnerSpace app, can cause this. Whether the change is on the console is unknown. Read the plan (`innerspace_list_walls`, or `innerspace_get_project` with `include_shapes`) before retrying. A repeated create whose first call did land is reported as already applied and sends nothing.

### "the console refused the session, so the change was not sent"

The session had expired. The server logged in again but did not resend the write, so nothing changed. Send the same call again.

### "the console account cannot make this change"

The console refused the write again on the session it had just issued: the account can read InnerSpace but not change it. Nothing was sent again and nothing changed. Use an account that can edit InnerSpace, such as a Super Admin.

## Network and TLS

### Certificate errors

The connection error for a failed certificate check names `UNIFI_INNERSPACE_SSL_FINGERPRINT` (or `UNIFI_SSL_FINGERPRINT`) and `UNIFI_INNERSPACE_VERIFY_SSL`, and carries no host, port or fingerprint.

- **Verification is on and the console has a self-signed certificate.** Pin its SHA-256 fingerprint, or set `UNIFI_INNERSPACE_VERIFY_SSL=false`.
- **A pin is set and the certificate changed.** The console certificate was regenerated, or something is intercepting the connection. Confirm the change is expected, then update the pin. A pin overrides `UNIFI_INNERSPACE_VERIFY_SSL`.

With verification off and no pin, the server logs one warning at its first connection. That is not an error; it means nothing checks who is answering. See [TLS verification](../../../docs/tls-verification.md).

### Timeouts

One request waits up to 30 seconds, and a login attempt 15. Check that the console is reachable and not overloaded.

## Missing tools

### A tool is not in the client's tool list

1. If only `innerspace_setup_status` is listed, no host is set (see above).
2. In `meta_only` mode no domain tool is listed; reach them through `innerspace_execute`, or switch to the default `lazy` mode. In `lazy` mode the write tools are not listed directly: reach them through `innerspace_execute`, or list them with `innerspace_load_tools`.
3. In `eager` mode, `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS` may be filtering them out.
4. Some clients cache the tool list. Start a new session after changing the registration mode.

`innerspace_tool_index` lists every tool the server has, with `category`, `search` and `include_schemas` filters. See [MCP discovery and meta-tools](../../../docs/tool-index.md).

### The client asks for approval for `innerspace_execute`, or refuses it

`innerspace_execute` and `innerspace_batch` are not marked read-only, because a dispatcher cannot promise what it will run. To read, call the tool by name instead; the nine read tools are listed directly in the default lazy mode and are marked read-only. The write tools are reached through the dispatcher, so approving it is the approval for the write. See [permissions.md](permissions.md#meta-tools-and-read-only-clients).

## Docker

The published image is `ghcr.io/sirkirby/unifi-innerspace-mcp`. The Compose service builds the image from a checkout; see [configuration.md](configuration.md#docker-compose). The service is in the opt-in `innerspace` profile, so the default stack does not start it, and it is not in the relay's default server list.

```bash
docker compose -f docker/docker-compose.yml --profile innerspace up --build unifi-innerspace-mcp
```

The service mounts no files. A `_FILE` credential needs a read-only mount added in an override file; see [configuration.md](configuration.md#docker-compose). Without one, pass `UNIFI_INNERSPACE_PASSWORD`.

### The container exits immediately

Read `docker logs unifi-innerspace-mcp`. A `[credentials]` error means a credential provider could not be resolved: inside a container a `_FILE` path must point to a secret mounted into the container, and a `_COMMAND` helper must be installed in the image. With no host the container keeps running in setup mode.

### No bearer token

The service enables HTTP and passes `UNIFI_INNERSPACE_MCP_HTTP_AUTH_TOKEN` and `UNIFI_MCP_HTTP_AUTH_TOKEN` through only when they are set in your shell. It does not generate a token. Without one, any container on the Compose network can read the floor plans. Export a token of at least 32 printable characters before `docker compose up`. A token that is set but empty or too short refuses startup.

### Cannot reach the console from the container

The container needs HTTPS to the console on your network and does not read the shared `.env` file. Set `UNIFI_INNERSPACE_HOST`, the username and the password in your shell (or in `docker/.env`), and use an address the container can route to; `localhost` inside the container is the container.

### Cannot connect to port 3005

The service is published on `127.0.0.1:3005` only, so it is reachable from the Docker host, not from other machines. If a request is refused with a Host header error, add the host name you use to `UNIFI_MCP_ALLOWED_HOSTS`.

## Debug logging

```bash
export UNIFI_MCP_LOG_LEVEL=DEBUG
export UNIFI_MCP_DIAGNOSTICS=true
```

Logs go to stderr; stdout is reserved for MCP messages in stdio mode. Diagnostics add one line per tool call with its name, duration and outcome, never its arguments or result. Logs carry the operation, a route template and the exception class, never a response body, the console address, a request path or an exception's text.

## Reporting a problem

There is no support bundle for this server. Open a bug report and fill in the manual fields: the tool name, the error text, the server version or commit, the registration mode and transport, and the console and InnerSpace versions (from `innerspace_get_status`). Do not include your password, the console address, MAC addresses, serial numbers, plan or device names, or plan images.
