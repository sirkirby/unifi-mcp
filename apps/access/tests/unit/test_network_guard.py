"""The test-suite network guard refuses non-loopback access and records it."""

import socket

import pytest
import unifi_test_guard


def _take_blocked() -> list[str]:
    blocked = list(unifi_test_guard.blocked_network_access())
    unifi_test_guard.blocked_network_access().clear()
    return blocked


def test_connect_to_a_non_loopback_address_is_refused_and_recorded():
    sock = socket.socket()
    try:
        with pytest.raises(ConnectionRefusedError, match="test network guard"):
            sock.connect(("192.0.2.1", 443))
    finally:
        sock.close()
    assert _take_blocked() == ["192.0.2.1:443"]


def test_lookup_of_a_non_local_name_is_refused_and_recorded():
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("unifi.example.invalid", 443)
    assert _take_blocked() == ["DNS lookup of 'unifi.example.invalid'"]


def test_loopback_stays_available():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket()
    try:
        client.connect(server.getsockname())
    finally:
        client.close()
        server.close()
    assert socket.getaddrinfo("localhost", 0)
    assert _take_blocked() == []


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "::1", "::ffff:127.0.0.1", "[::1]", "localhost", "localhost.localdomain"]
)
def test_loopback_spellings_are_allowed(host):
    assert unifi_test_guard._is_loopback(host)


@pytest.mark.parametrize("host", ["192.0.2.1", "::ffff:192.0.2.1", "10.0.0.1", "example.invalid", None])
def test_non_loopback_hosts_are_not(host):
    assert not unifi_test_guard._is_loopback(host)


def test_only_loopback_access_hosts_are_ever_configured():
    import os

    # Inherited settings are scrubbed at conftest import; tests may only set loopback hosts.
    assert os.environ.get("UNIFI_ACCESS_HOST", "") in ("", "127.0.0.1")


@pytest.mark.asyncio
async def test_runtime_connection_manager_does_not_reconnect_unless_a_test_opts_in():
    from unifi_access_mcp.runtime import connection_manager

    assert connection_manager.host in ("", "127.0.0.1")
    assert await connection_manager.reconnect() is False
