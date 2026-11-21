"""Bearer-token exemption for trusted networks (UNIFI_MCP_HTTP_AUTH_TRUSTED_NETWORKS).

A reverse proxy or tunnel that authenticates callers itself (Cloudflare Access,
an ingress, a relay sidecar) cannot always add the server's static token. Its
requests skip the token when their TCP peer address is in a trusted network;
everything else still needs it.
"""

import asyncio
import ipaddress
import logging
import socket
from contextlib import suppress
from unittest.mock import patch

import httpx2 as httpx
import pytest
import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from unifi_mcp_shared.server import UniFiMCPServer
from unifi_mcp_shared.transport import (
    HTTP_AUTH_TRUSTED_NETWORKS_ENV,
    BearerTokenMiddleware,
    resolve_http_auth_trusted_networks,
    run_transports,
)

TOKEN = "t" * 40
LOGGER = logging.getLogger("test-trusted-networks")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(HTTP_AUTH_TRUSTED_NETWORKS_ENV, raising=False)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "  ", " , "])
def test_unset_or_blank_trusts_nothing(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv(HTTP_AUTH_TRUSTED_NETWORKS_ENV, value)
    assert resolve_http_auth_trusted_networks(logger=LOGGER) == ()


def test_parses_addresses_networks_and_ipv6(monkeypatch):
    monkeypatch.setenv(HTTP_AUTH_TRUSTED_NETWORKS_ENV, " 172.30.33.2/23, 10.0.0.5 ,fd00::/8, 172.30.32.0/23 ")

    assert resolve_http_auth_trusted_networks(logger=LOGGER) == (
        ipaddress.ip_network("172.30.32.0/23"),
        ipaddress.ip_network("10.0.0.5/32"),
        ipaddress.ip_network("fd00::/8"),
    )


@pytest.mark.parametrize("entry", ["not-an-ip", "300.1.1.1", "10.0.0.0/33", "example.com"])
def test_invalid_entry_refuses_startup(monkeypatch, caplog, entry):
    monkeypatch.setenv(HTTP_AUTH_TRUSTED_NETWORKS_ENV, f"172.30.32.0/23,{entry}")

    with pytest.raises(SystemExit) as excinfo:
        resolve_http_auth_trusted_networks(logger=LOGGER)

    assert excinfo.value.code == 2
    assert "is not an IP address or CIDR network" in caplog.text


@pytest.mark.parametrize("entry", ["0.0.0.0/0", "::/0", "1.2.3.4/0"])
def test_network_trusting_everything_refuses_startup(monkeypatch, caplog, entry):
    monkeypatch.setenv(HTTP_AUTH_TRUSTED_NETWORKS_ENV, entry)

    with pytest.raises(SystemExit) as excinfo:
        resolve_http_auth_trusted_networks(logger=LOGGER)

    assert excinfo.value.code == 2
    assert "trusts every address" in caplog.text


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


def _client(peer, networks, calls):
    async def app(scope, receive, send):
        calls.append(scope["type"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BearerTokenMiddleware(app, TOKEN, logger=LOGGER, trusted_networks=networks)
    transport = httpx.ASGITransport(app=middleware, client=peer)
    return httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1")


PROXY_NET = (ipaddress.ip_network("172.30.32.0/23"),)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("peer", "headers"),
    [
        (("172.30.33.2", 40000), {}),
        # The proxy's own Authorization header (its OAuth token) is not the server's token.
        (("172.30.33.2", 40000), {"Authorization": "Bearer proxy-issued-oauth-token"}),
        (("::ffff:172.30.33.2", 40000), {}),
    ],
)
async def test_trusted_peer_passes_without_the_token(peer, headers):
    calls: list[str] = []
    async with _client(peer, PROXY_NET, calls) as client:
        response = await client.post("/mcp", headers=headers)

    assert response.status_code == 200
    assert calls == ["http"]


@pytest.mark.asyncio
@pytest.mark.parametrize("peer", [("192.168.1.41", 50000), ("172.30.34.1", 50000), ("fe80::1", 50000)])
async def test_untrusted_peer_still_needs_the_token(peer):
    calls: list[str] = []
    async with _client(peer, PROXY_NET, calls) as client:
        rejected = await client.post("/mcp")
        accepted = await client.post("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert calls == ["http"]


@pytest.mark.asyncio
async def test_without_trusted_networks_every_peer_needs_the_token():
    calls: list[str] = []
    async with _client(("172.30.33.2", 40000), (), calls) as client:
        response = await client.post("/mcp")

    assert response.status_code == 401
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("client", [None, ("not-an-address", 1)])
async def test_unknown_peer_is_not_trusted(client):
    sent: list[dict] = []

    async def app(scope, receive, send):  # pragma: no cover - must not run
        raise AssertionError("request reached the app")

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    middleware = BearerTokenMiddleware(app, TOKEN, logger=LOGGER, trusted_networks=PROXY_NET)
    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": [], "client": client}
    await middleware(scope, receive, send)

    assert sent[0]["status"] == 401


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_value_refuses_startup_before_any_transport(monkeypatch):
    monkeypatch.setenv(HTTP_AUTH_TRUSTED_NETWORKS_ENV, "nonsense")
    server = UniFiMCPServer("trusted-startup-test")

    with patch("unifi_mcp_shared.transport._serve_authenticated_http") as serve:
        with pytest.raises(SystemExit) as excinfo:
            await run_transports(
                server=server,
                http_enabled=True,
                host="127.0.0.1",
                port=_free_port(),
                http_transport="streamable-http",
                logger=LOGGER,
                auth_token=TOKEN,
            )

    assert excinfo.value.code == 2
    serve.assert_not_called()


@pytest.mark.asyncio
async def test_trusted_networks_without_a_token_warn_and_change_nothing(monkeypatch, caplog):
    monkeypatch.setenv(HTTP_AUTH_TRUSTED_NETWORKS_ENV, "172.30.32.0/23")
    server = UniFiMCPServer("trusted-no-token-test")

    async def fake_serve(**_kwargs):
        return None

    with (
        patch("unifi_mcp_shared.transport.os.getpid", return_value=1),
        patch.object(server, "run_streamable_http_async", side_effect=fake_serve) as plain,
        patch("unifi_mcp_shared.transport._serve_authenticated_http") as authenticated,
    ):
        await run_transports(
            server=server,
            http_enabled=True,
            host="127.0.0.1",
            port=_free_port(),
            http_transport="streamable-http",
            logger=LOGGER,
        )

    assert "has no effect" in caplog.text
    plain.assert_called_once()
    authenticated.assert_not_called()


# ---------------------------------------------------------------------------
# Real server
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def _serve(monkeypatch, trusted: str):
    monkeypatch.setenv(HTTP_AUTH_TRUSTED_NETWORKS_ENV, trusted)
    server = UniFiMCPServer(
        "trusted-real-test",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    port = _free_port()
    real_uvicorn_server = uvicorn.Server
    holder: dict[str, uvicorn.Server] = {}

    def capture(config: uvicorn.Config) -> uvicorn.Server:
        holder["server"] = real_uvicorn_server(config)
        return holder["server"]

    patches = (
        patch("unifi_mcp_shared.transport.os.getpid", return_value=1),
        patch("uvicorn.Server", side_effect=capture),
    )
    for p in patches:
        p.start()
    task = asyncio.create_task(
        run_transports(
            server=server,
            http_enabled=True,
            host="127.0.0.1",
            port=port,
            http_transport="streamable-http",
            logger=LOGGER,
            auth_token=TOKEN,
        )
    )
    for _ in range(200):
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.01)
            continue
        writer.close()
        await writer.wait_closed()
        break
    else:
        raise RuntimeError("test server did not start")

    async def stop():
        if "server" in holder:
            holder["server"].should_exit = True
        try:
            await asyncio.wait_for(task, timeout=3.0)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for p in patches:
            p.stop()

    return f"http://127.0.0.1:{port}/mcp", stop


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_real_server_lets_a_trusted_peer_in_without_the_token(monkeypatch):
    url, stop = await _serve(monkeypatch, "127.0.0.1/32")
    try:
        async with httpx.AsyncClient() as raw:
            response = await raw.post(url, json=INIT, headers=MCP_HEADERS)
        assert response.status_code == 200
    finally:
        await stop()


@pytest.mark.asyncio
async def test_real_server_ignores_a_forwarded_for_header_claiming_a_trusted_source(monkeypatch):
    # The peer is 127.0.0.1 (uvicorn's default forwarded_allow_ips), and the header
    # claims a trusted address. Only the TCP peer counts, so the token is required.
    url, stop = await _serve(monkeypatch, "10.0.0.0/8")
    try:
        async with httpx.AsyncClient() as raw:
            spoofed = await raw.post(url, json=INIT, headers={**MCP_HEADERS, "X-Forwarded-For": "10.1.2.3"})
            with_token = await raw.post(url, json=INIT, headers={**MCP_HEADERS, "Authorization": f"Bearer {TOKEN}"})
        assert spoofed.status_code == 401
        assert with_token.status_code == 200
    finally:
        await stop()
