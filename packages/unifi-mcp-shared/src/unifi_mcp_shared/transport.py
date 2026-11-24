"""Shared transport lifecycle management for MCP servers.

Handles running stdio and HTTP transports concurrently with proper lifecycle
coupling: when one transport exits, the other is cancelled. This prevents
orphaned processes when a stdio client disconnects while the HTTP server is
still listening.

Also catches ``SystemExit`` from uvicorn bind failures (e.g. port conflict)
so that a failed HTTP transport does not kill the stdio connection.

HTTP can optionally require a static bearer token
(``UNIFI_MCP_HTTP_AUTH_TOKEN``); see :func:`resolve_http_auth_token`.
Requests from networks listed in ``UNIFI_<PREFIX>_MCP_HTTP_AUTH_TRUSTED_NETWORKS``
or ``UNIFI_MCP_HTTP_AUTH_TRUSTED_NETWORKS`` (an authenticating reverse proxy or
tunnel in front of the server) skip that token; see
:func:`resolve_http_auth_trusted_networks`.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import os
from typing import TYPE_CHECKING, Any

from unifi_core.config_helpers import parse_config_bool

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer
    from starlette.types import ASGIApp, Receive, Scope, Send

# Set to false to serve HTTP alone from a process that is not PID 1 (an
# init-managed container, a service manager). Empty counts as unset.
STDIO_ENABLED_ENV = "UNIFI_MCP_STDIO_ENABLED"

VALID_HTTP_TRANSPORTS = {"streamable-http", "sse"}
_TRANSPORT_LABELS = {"streamable-http": "Streamable HTTP", "sse": "HTTP SSE"}

# Resolved by bootstrap.resolve_env as UNIFI_<PREFIX>_MCP_HTTP_AUTH_TOKEN, then
# UNIFI_MCP_HTTP_AUTH_TOKEN, each also accepting the _FILE and _COMMAND spellings.
HTTP_AUTH_TOKEN_KEY = "mcp_http_auth_token"
MIN_HTTP_AUTH_TOKEN_LENGTH = 32

# Comma-separated IP addresses or CIDR networks whose requests skip the bearer
# token, because a reverse proxy or tunnel there authenticates callers itself.
# Matched against the TCP peer address; read from the environment only, as
# UNIFI_<PREFIX>_MCP_HTTP_AUTH_TRUSTED_NETWORKS and then this shared spelling.
HTTP_AUTH_TRUSTED_NETWORKS_ENV = "UNIFI_MCP_HTTP_AUTH_TRUSTED_NETWORKS"

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
_IPV4_MAPPED = ipaddress.IPv6Network("::ffff:0:0/96")
_AUTH_REALM = "unifi-mcp"


def resolve_http_config(
    server_cfg: Any,
    *,
    default_port: int = 3000,
    logger: logging.Logger,
) -> tuple[bool, str, str, int]:
    """Parse HTTP transport settings from the server config block.

    Returns ``(http_enabled, http_transport, host, port)`` with validation
    applied (invalid transport falls back to ``streamable-http``, PID-1 check
    may disable HTTP).
    """
    host = server_cfg.get("host", "127.0.0.1")
    port = int(server_cfg.get("port", default_port))
    http_cfg = server_cfg.get("http", {})
    http_enabled = parse_config_bool(http_cfg.get("enabled", False))

    http_transport = http_cfg.get("transport", "streamable-http")
    if isinstance(http_transport, str):
        http_transport = http_transport.lower()
    if http_transport not in VALID_HTTP_TRANSPORTS:
        logger.warning(
            "Invalid UNIFI_MCP_HTTP_TRANSPORT: '%s'. Defaulting to 'streamable-http'.",
            http_transport,
        )
        http_transport = "streamable-http"

    transport_label = _TRANSPORT_LABELS[http_transport]

    # Only the main container process (PID 1) should bind the HTTP port,
    # unless http.force=true is set in config (for local development/testing).
    force_http = parse_config_bool(http_cfg.get("force", False))
    is_main_container_process = os.getpid() == 1
    if http_enabled and not is_main_container_process and not force_http:
        logger.info(
            "%s enabled in config but skipped in exec session (PID %s != 1). "
            "Set UNIFI_MCP_HTTP_FORCE=true to override.",
            transport_label,
            os.getpid(),
        )
        http_enabled = False

    return http_enabled, http_transport, host, port


def resolve_http_auth_token(*, env_prefix: str, logger: logging.Logger, configured: Any = None) -> str | None:
    """Resolve the optional bearer token that HTTP callers must present.

    Checks ``UNIFI_<PREFIX>_MCP_HTTP_AUTH_TOKEN`` and then the shared
    ``UNIFI_MCP_HTTP_AUTH_TOKEN``; both accept the ``_FILE`` and ``_COMMAND``
    spellings that the controller credentials do. ``configured`` is
    ``server.http.auth_token`` from ``config.yaml``, used only when no
    environment spelling is set. Returns ``None`` when no token is configured,
    which leaves HTTP unauthenticated as before.

    A spelling that is present but empty refuses startup instead of counting as
    unset: this is an access control, and a secret store that materialises a
    missing secret as ``""`` must not silently turn authentication off.

    A token shorter than :data:`MIN_HTTP_AUTH_TOKEN_LENGTH` characters, or one
    holding whitespace or non-printable/non-ASCII characters (which a client
    cannot send in an ``Authorization`` header), refuses startup rather than
    serving a token nobody can present or anybody can guess.
    """
    from unifi_mcp_shared.bootstrap import EXIT_SECRET_UNRESOLVED, resolve_env

    token = resolve_env(HTTP_AUTH_TOKEN_KEY, env_prefix=env_prefix, logger=logger)
    if token is None:
        upper = HTTP_AUTH_TOKEN_KEY.upper()
        empty = [
            f"{base}{suffix}"
            for base in (f"UNIFI_{env_prefix}_{upper}", f"UNIFI_{upper}")
            for suffix in ("", "_FILE", "_COMMAND")
            if os.environ.get(f"{base}{suffix}") == ""
        ]
        if empty:
            logger.error(
                "[credentials] %s is set but empty. Set a token or unset the variable. "
                "Refusing to start until it is fixed.",
                " and ".join(empty),
            )
            raise SystemExit(EXIT_SECRET_UNRESOLVED)
        token = str(configured) if configured else None
    if token is None:
        return None
    if not (token.isascii() and token.isprintable()) or any(ch.isspace() for ch in token):
        logger.error(
            "[credentials] The HTTP auth token must be printable ASCII with no whitespace. "
            "Refusing to start until it is fixed."
        )
        raise SystemExit(EXIT_SECRET_UNRESOLVED)
    if len(token) < MIN_HTTP_AUTH_TOKEN_LENGTH:
        logger.error(
            "[credentials] The HTTP auth token is %d characters; use at least %d (for example `openssl rand -hex 32`). "
            "Refusing to start until it is fixed.",
            len(token),
            MIN_HTTP_AUTH_TOKEN_LENGTH,
        )
        raise SystemExit(EXIT_SECRET_UNRESOLVED)
    return token


def _trusted_networks_setting(env_prefix: str | None) -> tuple[str, str | None]:
    """The variable that sets this server's trusted networks, and its raw value.

    ``UNIFI_<PREFIX>_MCP_HTTP_AUTH_TRUSTED_NETWORKS`` wins whenever it is
    present, even empty: an empty server-level value means no network skips
    the token on this server, whatever the shared
    ``UNIFI_MCP_HTTP_AUTH_TRUSTED_NETWORKS`` says. This differs from the token
    and the credentials, where empty counts as unset; here the empty value
    narrows access, so honouring it fails closed. Without ``env_prefix`` only
    the shared variable is read.
    """
    if env_prefix:
        server_var = f"UNIFI_{env_prefix}_MCP_HTTP_AUTH_TRUSTED_NETWORKS"
        if server_var in os.environ:
            return server_var, os.environ[server_var]
    return HTTP_AUTH_TRUSTED_NETWORKS_ENV, os.environ.get(HTTP_AUTH_TRUSTED_NETWORKS_ENV)


def resolve_http_auth_trusted_networks(
    *, logger: logging.Logger, env_prefix: str | None = None
) -> tuple[IPNetwork, ...]:
    """Parse this server's trusted networks into networks.

    The value comes from :func:`_trusted_networks_setting`: the
    server-level variable when present, else the shared one. Each
    comma-separated entry is an IP address or a CIDR network (host bits are
    ignored, so ``192.0.2.7/24`` means ``192.0.2.0/24``). Unset or blank means
    no network is trusted. Startup is refused, naming the variable that was
    read, because this is an access control and a typo must not silently widen
    or drop it, when:

    - an entry does not parse;
    - an entry is an IPv4-mapped IPv6 network (``::ffff:a.b.c.d``), which could
      never match because mapped peers are compared in their IPv4 form;
    - the entries trust every IPv4 or every IPv6 address, alone (``/0``) or
      together (``0.0.0.0/1`` plus ``128.0.0.0/1``), which turns the token off.
    """
    var, raw = _trusted_networks_setting(env_prefix)
    if raw is None or not raw.strip():
        if var != HTTP_AUTH_TRUSTED_NETWORKS_ENV and (os.environ.get(HTTP_AUTH_TRUSTED_NETWORKS_ENV) or "").strip():
            logger.info("%s is empty, so this server does not use %s.", var, HTTP_AUTH_TRUSTED_NETWORKS_ENV)
        return ()
    networks: list[IPNetwork] = []
    for entry in (part.strip() for part in raw.split(",")):
        if not entry:
            continue
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            logger.error(
                "[credentials] %s entry %r is not an IP address or CIDR network. Refusing to start until it is fixed.",
                var,
                entry,
            )
            raise SystemExit(2) from None
        if network.prefixlen == 0:
            logger.error(
                "[credentials] %s entry %r trusts every address, which turns the bearer token off. "
                "Unset the token instead, or list the proxy's own address. Refusing to start until it is fixed.",
                var,
                entry,
            )
            raise SystemExit(2)
        if isinstance(network, ipaddress.IPv6Network) and network.subnet_of(_IPV4_MAPPED):
            mapped = network.network_address.ipv4_mapped
            logger.error(
                "[credentials] %s entry %r is an IPv4-mapped IPv6 network; write it as %s. "
                "Refusing to start until it is fixed.",
                var,
                entry,
                ipaddress.ip_network(f"{mapped}/{network.prefixlen - 96}"),
            )
            raise SystemExit(2)
        if network not in networks:
            networks.append(network)
    for version in (4, 6):
        same_version = [network for network in networks if network.version == version]
        if any(merged.prefixlen == 0 for merged in ipaddress.collapse_addresses(same_version)):
            logger.error(
                "[credentials] %s entries together trust every IPv%d address, which turns the bearer token off. "
                "Unset the token instead, or list the proxy's own address. Refusing to start until it is fixed.",
                var,
                version,
            )
            raise SystemExit(2)
    return tuple(networks)


def _peer_in(scope: Scope, networks: tuple[IPNetwork, ...]) -> bool:
    """Whether the request's TCP peer address falls in one of ``networks``."""
    if not networks:
        return False
    client = scope.get("client")
    if not client:
        return False
    try:
        address = ipaddress.ip_address(client[0])
    except (TypeError, ValueError):
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in networks)


class BearerTokenMiddleware:
    """Reject every HTTP request that does not carry ``Authorization: Bearer <token>``.

    Wraps the whole Starlette app, so it covers every method and path of both
    transports (``/mcp``, ``/sse``, ``/messages/``). Lifespan events pass through
    untouched: the Streamable HTTP session manager starts there.

    Requests whose TCP peer address is in ``trusted_networks`` pass without a
    token: an authenticating proxy or tunnel there has already checked the
    caller, and may itself use ``Authorization`` for its own credentials.
    """

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        *,
        logger: logging.Logger,
        trusted_networks: tuple[IPNetwork, ...] = (),
    ) -> None:
        self._app = app
        self._token = token.encode("ascii")
        self._logger = logger
        self._trusted_networks = tuple(trusted_networks)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        if _peer_in(scope, self._trusted_networks):
            await self._app(scope, receive, send)
            return
        values = [value for name, value in scope.get("headers", []) if name == b"authorization"]
        if not values:
            await self._reject(scope, send, error=None)
            return
        scheme, _, credentials = values[0].partition(b" ")
        valid = (
            len(values) == 1
            and scheme.lower() == b"bearer"
            and hmac.compare_digest(credentials.strip(b" "), self._token)
        )
        if not valid:
            await self._reject(scope, send, error="invalid_token")
            return
        await self._app(scope, receive, send)

    async def _reject(self, scope: Scope, send: Send, *, error: str | None) -> None:
        # Fixed text only: never log the presented credential or the peer address.
        self._logger.warning("Rejected an HTTP request with a missing or invalid bearer token.")
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        challenge = f'Bearer realm="{_AUTH_REALM}"' + (f', error="{error}"' if error else "")
        body = json.dumps({"error": error or "unauthorized"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", challenge.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


async def _serve_authenticated_http(
    *,
    server: MCPServer,
    host: str,
    port: int,
    http_transport: str,
    auth_token: str,
    logger: logging.Logger,
    trusted_networks: tuple[IPNetwork, ...] = (),
) -> None:
    """Build the SDK's Starlette app, wrap it in bearer auth, and serve it.

    Mirrors ``run_streamable_http_async`` / ``run_sse_async`` with the default
    paths; the SDK has no hook for an outer middleware short of its OAuth
    resource-server profile.

    With trusted networks, uvicorn's ``X-Forwarded-For`` handling is turned
    off, so the address checked is always the TCP peer and a header cannot
    claim a trusted source.
    """
    import uvicorn

    transport_security = getattr(server, "transport_security", None)
    if http_transport == "streamable-http":
        app = server.streamable_http_app(transport_security=transport_security, host=host)
    else:
        app = server.sse_app(transport_security=transport_security, host=host)
    config = uvicorn.Config(
        BearerTokenMiddleware(app, auth_token, logger=logger, trusted_networks=trusted_networks),
        host=host,
        port=port,
        log_level=server.settings.log_level.lower(),
        **({"proxy_headers": False} if trusted_networks else {}),
    )
    await uvicorn.Server(config).serve()


async def run_transports(
    *,
    server: MCPServer,
    http_enabled: bool,
    host: str,
    port: int,
    http_transport: str,
    logger: logging.Logger,
    auth_token: str | None = None,
    env_prefix: str | None = None,
) -> None:
    """Run stdio and optionally HTTP, with stdio as the primary.

    Stdio is the primary transport — Claude Code (and any other stdio MCP
    client) talks to the server over it.  HTTP, when enabled, is a side
    channel that runs as a background task: if HTTP fails (port conflict,
    bind error, etc.) stdio keeps serving.  When stdio exits, HTTP is
    cancelled so the process terminates cleanly.

    ``SystemExit`` raised by uvicorn on port-bind failures is caught inside
    ``run_http`` so it does not propagate.

    When ``auth_token`` is set (see :func:`resolve_http_auth_token`), every HTTP
    request must carry it as ``Authorization: Bearer <token>``, except requests
    from this server's trusted networks (see
    :func:`resolve_http_auth_trusted_networks`; ``env_prefix`` selects the
    server-level ``UNIFI_<PREFIX>_MCP_HTTP_AUTH_TRUSTED_NETWORKS`` spelling, and
    without it only the shared variable is read); stdio is unaffected.

    The main process of a container (PID 1) has no stdio client and runs HTTP
    alone. ``UNIFI_MCP_STDIO_ENABLED=false`` takes the same HTTP-only path for
    any process; it needs HTTP to be enabled, or startup is refused because
    nothing would serve.
    """

    stdio_enabled = parse_config_bool(os.environ.get(STDIO_ENABLED_ENV) or None, default=True)
    if not stdio_enabled and not http_enabled:
        logger.error(
            "%s=false turns stdio off, but HTTP is not enabled, so nothing would serve. "
            "Set UNIFI_MCP_HTTP_ENABLED=true, plus UNIFI_MCP_HTTP_FORCE=true when the server is not "
            "a container's main process (PID 1). Refusing to start.",
            STDIO_ENABLED_ENV,
        )
        raise SystemExit(2)

    # Resolved before any transport starts, so an invalid value refuses startup
    # instead of being caught as an HTTP failure below.
    trusted_networks: tuple[IPNetwork, ...] = ()
    trusted_var, trusted_raw = _trusted_networks_setting(env_prefix)
    if http_enabled and auth_token:
        trusted_networks = resolve_http_auth_trusted_networks(logger=logger, env_prefix=env_prefix)
    elif http_enabled and (trusted_raw or "").strip():
        logger.warning(
            "%s is set, but no HTTP bearer token is configured, so it has no effect: HTTP is unauthenticated.",
            trusted_var,
        )

    async def run_stdio() -> None:
        logger.info("Starting FastMCP stdio server ...")
        await server.run_stdio_async()

    if not http_enabled:
        try:
            await run_stdio()
            logger.info("FastMCP stdio server exited.")
        except Exception as e:
            logger.error("Error running FastMCP stdio server: %s", e, exc_info=True)
            raise
        return

    transport_label = _TRANSPORT_LABELS.get(http_transport, http_transport)

    async def run_http() -> None:
        try:
            logger.info("Starting FastMCP %s server on %s:%s ...", transport_label, host, port)
            # Redirect uvicorn access logs to stderr to prevent stdout conflicts
            # when running alongside stdio transport (stdout is used for JSON-RPC)
            import uvicorn.config

            uvicorn.config.LOGGING_CONFIG["handlers"]["access"]["stream"] = "ext://sys.stderr"

            if auth_token:
                if trusted_networks:
                    # WARNING, not INFO: an exemption from authentication must stay
                    # visible when the log level is raised to WARNING.
                    logger.warning(
                        "%s requires a bearer token, except from %s (%s).",
                        transport_label,
                        ", ".join(str(network) for network in trusted_networks),
                        trusted_var,
                    )
                else:
                    logger.info("%s requires a bearer token.", transport_label)
                await _serve_authenticated_http(
                    server=server,
                    host=host,
                    port=port,
                    http_transport=http_transport,
                    auth_token=auth_token,
                    logger=logger,
                    trusted_networks=trusted_networks,
                )
            elif http_transport == "streamable-http":
                await server.run_streamable_http_async(
                    host=host,
                    port=port,
                    transport_security=getattr(server, "transport_security", None),
                )
            else:
                await server.run_sse_async(
                    host=host,
                    port=port,
                    transport_security=getattr(server, "transport_security", None),
                )
            logger.info("%s server exited.", transport_label)
        except SystemExit as se:
            logger.error(
                "FastMCP %s server exited with SystemExit (code %s) — likely a port conflict on %s:%s",
                transport_label,
                se.code,
                host,
                port,
            )
        except Exception as http_e:
            logger.error("FastMCP %s server failed to start: %s", transport_label, http_e, exc_info=True)

    # When running as PID 1 (Docker container main process), stdin has no
    # client — stdio would exit immediately via EOF and cancel the HTTP
    # transport.  Run HTTP-only in this case, or when stdio is turned off.
    is_main_container_process = os.getpid() == 1
    if is_main_container_process or not stdio_enabled:
        if is_main_container_process:
            logger.info("Container main process (PID 1): running %s transport only.", transport_label)
        else:
            logger.info("%s=false: running %s transport only.", STDIO_ENABLED_ENV, transport_label)
        try:
            await run_http()
            logger.info("FastMCP %s server exited.", transport_label)
        except Exception as e:
            logger.error("Error running FastMCP %s server: %s", transport_label, e, exc_info=True)
            raise
        return

    # Run HTTP as a background task and await stdio in the main flow.  If
    # HTTP fails (port conflict, etc.) the failure is contained inside
    # run_http (which logs and returns), the http_task completes, and stdio
    # keeps serving.  When stdio exits — for any reason — we cancel HTTP so
    # we don't leave an orphan listener behind.
    http_task = asyncio.create_task(run_http(), name="http")
    # Yield once so http_task gets to start before stdio races to completion
    # in the (rare) case where stdio exits without ever awaiting.
    await asyncio.sleep(0)
    try:
        await run_stdio()
        logger.info("FastMCP stdio server exited.")
    finally:
        if not http_task.done():
            logger.info("Stdio transport exited; cancelling HTTP transport.")
            http_task.cancel()
            try:
                await http_task
            except asyncio.CancelledError:
                pass
            except Exception as http_e:
                logger.warning("HTTP task error during shutdown: %s", http_e)
        elif (http_exc := http_task.exception()) is not None:
            # run_http normally swallows uvicorn errors and returns; this branch
            # only fires for unexpected exceptions that escaped its try/except.
            logger.warning("HTTP task exited with unhandled error: %s", http_exc)
