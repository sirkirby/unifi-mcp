# Troubleshooting — Drive Server

This server has no support-bundle tool. To report a problem, see [Reporting a problem](#reporting-a-problem).

## Setup and startup

### The server lists only `drive_setup_status`

No NAS host is set, so the server is in setup mode. Set `UNIFI_DRIVE_HOST`, `UNIFI_DRIVE_USERNAME` and a `UNIFI_DRIVE_PASSWORD*` provider, and restart the server. The shared `UNIFI_HOST` does not count: it names the gateway, and this server never reads it. Setup mode makes no request to the NAS.

After changing a setting:

1. Restart the server. For a stdio server, that means restarting the client or starting a new session, since the client launches it.
2. Confirm the variable reaches the server's process. A variable exported in your shell does not reach a server launched by a desktop client; put it in the client's server entry or in the file named by `UNIFI_SETTINGS_FILE`.
3. Call `drive_setup_status` again if it is still listed. It reports what is missing without making any request.

### The server exits at startup

- **Exit code 2 and a log line naming `UNIFI_DRIVE_SSL_FINGERPRINT`.** The certificate pin is malformed. It must be a SHA-256 fingerprint. The log does not repeat the value.
- **A log line naming an operation gate variable** such as `UNIFI_DRIVE_READ_CONCURRENCY`. The value is not a number in its range; see [configuration.md](configuration.md#nas-operation-gate).
- **A `[credentials]` error.** A `_FILE` or `_COMMAND` password could not be resolved, or more than one spelling of the password is set. Keep exactly one. A `_FILE` path must exist, be a regular file and be readable from the server's point of view, including inside a container.
- **An HTTP auth token that is set but empty, shorter than 32 characters or malformed.** See [configuration.md](configuration.md#http-transport).
- **`CONFIG_PATH` is relative or names a missing file.** Use an absolute path to a YAML file you control, or unset it.

### The NAS is down at startup

The server does not contact the NAS at startup, so it starts and serves either way. The first tool call logs in; until the NAS answers, each call returns a connection error. You do not need to restart the server once the NAS is back.

## NAS login and access

### "rejected the configured username/password"

The NAS refused the login with HTTP 401 or 403. Check that:

- `UNIFI_DRIVE_HOST` is the NAS, not the gateway or a Cloud Key.
- The account is a **local** UniFi OS account on the NAS. A UI.com account with MFA cannot log in here.
- `UNIFI_DRIVE_USERNAME` and the password are the NAS's, not the gateway's. The server never falls back to `UNIFI_USERNAME` or `UNIFI_PASSWORD`.

### "Login attempts are paused"

After a rejected login the server waits before it tries again: 60 seconds, doubling with each further rejection up to 15 minutes. This keeps repeated tool calls from locking the account out. Fix the credentials and restart the server, or wait out the pause.

### "rate-limiting logins" or "rate-limiting requests" (429)

The NAS is throttling. Logins pause on the same schedule as a rejected one. Wait, and lower `UNIFI_DRIVE_READ_CONCURRENCY` if a batch triggered it.

### "refused ... (403). The account lacks permission"

The login works but the account may not make this request. Reads need an account that can open UniFi Drive; turning file services on or off and changing NFS clients need an administrator of Drive. Give the account that role on the NAS, or keep the server read-only with `UNIFI_DRIVE_READ_ONLY=true`.

### "login failed ... Check that the host is a UniFi OS console" or "has no endpoint ... (404)"

The host answered, but not like a UniFi OS console running Drive. Check the host and `UNIFI_DRIVE_PORT`, and that Drive is installed and current on the NAS. UniFi Drive has no published API; the server was checked against a UNAS Pro 8 on UniFi OS 5.0.12, and another firmware may differ.

### "answered ... with a redirect; not followed"

The server never follows redirects, so the session cookie cannot leave the NAS. A redirect usually means the host or port points at something other than the NAS's HTTPS port.

## File services and NFS

### Turning Time Machine on is refused

Time Machine runs over SMB. Turn SMB on first with `drive_set_file_service`, then Time Machine.

### Time Machine is off after SMB was turned off and on again

Turning SMB off turns Time Machine off too, and turning SMB back on leaves it off. The preview warns about this. Turn Time Machine on again with `drive_set_file_service`.

### "The NFS connection list changed since this change was planned"

Drive keeps every NFS client in one list and replaces it as a whole. Just before writing, the tool read the list again and found it different from the preview, for example after an edit in the Drive web app or another write. Nothing was written. Run the change again.

### "NFS can only export shared drives"

A personal drive cannot be exported over NFS. Pick a drive from `drive_list_shared_drives` whose type is shared.

### "rejected NFS client ..."

Before saving a client, the tool runs Drive's own hostname check, as the web app does, and Drive flagged this client. Check the address, hostname or range. The client may contain only letters, digits and `. : / * - _`, or be an IP address or range.

### "already has a connection" / "NFS connection ... not found"

A client can have one connection. Use `drive_update_nfs_connection` to change an existing one, and pass `client` exactly as `drive_list_nfs_connections` lists it.

### NFS clients still mount after NFS was turned off and on

Turning NFS off with this server keeps the client list, so the clients can mount again when NFS comes back on. The Drive web app clears the list instead. Remove clients with `drive_remove_nfs_connection` if you want the same.

### A mount fails on the client

Mount `<nas>:/var/nfs/shared/<Shared Drive Name>` over NFSv3; `drive_list_nfs_connections` returns each drive's `export_path`. Check that NFS is on (`drive_get_file_services`) and that the client's address matches the connection.

### A write returned `mutation_applied: null`

The change was sent and no answer came back in time. Read the state back (`drive_get_file_services` or `drive_list_nfs_connections`) before retrying. `mutation_applied: false` means nothing was sent.

## Network and TLS

### Certificate errors

The connection error for a failed certificate check names `UNIFI_DRIVE_SSL_FINGERPRINT` and `UNIFI_DRIVE_VERIFY_SSL`, and carries no host, port or fingerprint. It also mentions `UNIFI_SSL_FINGERPRINT`, as the startup warning does, but only `UNIFI_DRIVE_SSL_FINGERPRINT` pins the NAS.

- **Verification is on and the NAS has a self-signed certificate.** Pin its SHA-256 fingerprint, or set `UNIFI_DRIVE_VERIFY_SSL=false`.
- **A pin is set and the certificate changed.** The NAS certificate was regenerated, or something is intercepting the connection. Confirm the change is expected, then update the pin. A pin overrides `UNIFI_DRIVE_VERIFY_SSL`.
- **`UNIFI_SSL_FINGERPRINT` is set but the NAS still is not pinned.** That variable pins the gateway; the NAS takes only `UNIFI_DRIVE_SSL_FINGERPRINT`.

With verification off and no pin, the server logs one warning at startup. That is not an error; it means nothing checks who is answering. See [TLS verification](../../../docs/tls-verification.md).

### Timeouts

One request waits up to `UNIFI_DRIVE_TIMEOUT_SECONDS` (30 by default). Check that the NAS is reachable and not busy, for example rebuilding a pool. A confirmed write's requests also stop at the write budget (`UNIFI_DRIVE_WRITE_HOLD_SECONDS`).

## Missing tools

### A tool is not in the client's tool list

1. If only `drive_setup_status` is listed, no host is set (see above).
2. In the default `lazy` mode and in `meta_only` mode the domain tools are not listed; reach them through `drive_execute`, load them with `drive_load_tools`, or switch to `eager` mode.
3. In `eager` mode, `UNIFI_ENABLED_CATEGORIES` or `UNIFI_ENABLED_TOOLS` may be filtering them out. The categories are the tool modules: `system`, `storage`, `shared_drives`, `file_services`, `nfs`.
4. Some clients cache the tool list. Start a new session after changing the registration mode.

`drive_tool_index` lists every tool the server has, with `category`, `search` and `include_schemas` filters. See [MCP discovery and meta-tools](../../../docs/tool-index.md).

### The client asks for approval for `drive_execute`, or refuses it

`drive_execute` and `drive_batch` are not marked read-only, because they can run a write. Approve them, or run in `eager` mode so the reads are listed directly and marked read-only. See [permissions.md](permissions.md#meta-tools-and-read-only-clients).

## Docker

The published image is `ghcr.io/sirkirby/unifi-drive-mcp`. The Compose service builds the image from a checkout; see [configuration.md](configuration.md#docker-compose). The service is in the opt-in `drive` profile, so the default stack does not start it, and it is not in the relay's default server list.

```bash
docker compose -f docker/docker-compose.yml --profile drive up --build unifi-drive-mcp
```

The service mounts no files. A `_FILE` password needs a read-only mount added in an override file; see [configuration.md](configuration.md#docker-compose). Without one, pass `UNIFI_DRIVE_PASSWORD`.

### The container exits immediately

Read `docker logs unifi-drive-mcp`. A `[credentials]` error means the password provider could not be resolved: inside a container a `_FILE` path must point to a secret mounted into the container, and a `_COMMAND` helper must be installed in the image. With no host the container keeps running in setup mode.

### No bearer token

The service enables HTTP and passes `UNIFI_DRIVE_MCP_HTTP_AUTH_TOKEN` and `UNIFI_MCP_HTTP_AUTH_TOKEN` through only when they are set in your shell. It does not generate a token. Without one, any container on the Compose network can call the write tools with the NAS login. Export a token of at least 32 printable characters before `docker compose up`. A token that is set but empty or too short refuses startup.

### Cannot reach the NAS from the container

The container needs HTTPS to the NAS on your network and does not read the shared `.env` file. Set `UNIFI_DRIVE_HOST`, the username and the password in your shell (or in `docker/.env`), and use an address the container can route to; `localhost` inside the container is the container.

### Cannot connect to port 3004

The service is published on `127.0.0.1:3004` only, so it is reachable from the Docker host, not from other machines. If a request is refused with a Host header error, add the host name you use to `UNIFI_MCP_ALLOWED_HOSTS`.

## Debug logging

```bash
export UNIFI_MCP_LOG_LEVEL=DEBUG
export UNIFI_MCP_DIAGNOSTICS=true
```

Logs go to stderr; stdout is reserved for MCP messages in stdio mode. Diagnostics add one line per tool call with its name, duration and outcome, never its arguments or result. Error text never contains the NAS address or the credentials.

## Reporting a problem

There is no support bundle for this server: the bundle is one closed privacy schema shared by the Network, Protect and Access servers, and adding Drive would change that contract for all three. Open a bug report and fill in the manual fields: the tool name, the error text, the server version or commit, the registration mode and transport, and the NAS model and firmware (from `drive_get_system_info`, or `drive_setup_status` in setup mode). Do not include your password, the NAS address, NFS client addresses, shared drive names, disk serial numbers or MAC addresses.
