"""A failed certificate check on an ordinary Network request never reaches a tool response or log.

aiounifi wraps an aiohttp ``ClientError`` as ``RequestError("Error requesting
data from <url>: <error>")``, and a pin mismatch's text carries both
fingerprints. The connection manager's session replaces the failure before
aiounifi sees it; this drives a real tool through ``ConnectionManager.request``
and aiounifi over a session whose connector fails the way a stale pin does.
"""

import logging
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aiounifi.controller import Controller
from aiounifi.models.configuration import Configuration

from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.hotspot_manager import HotspotManager

HOST = "198.51.100.7"
PORT = 8443
EXPECTED = b"\xaa" * 32
RECEIVED = b"\xbb" * 32
DETAIL_MARKERS = [HOST, str(PORT), EXPECTED.hex(), RECEIVED.hex(), repr(EXPECTED), repr(RECEIVED)]


class _StalePinConnector(aiohttp.TCPConnector):
    async def _create_connection(self, req, traces, timeout):
        raise aiohttp.ServerFingerprintMismatch(EXPECTED, RECEIVED, HOST, PORT)


def _rendered(caplog) -> str:
    formatter = logging.Formatter("%(message)s")
    return "\n".join(formatter.format(record) for record in caplog.records)


@pytest.mark.asyncio
async def test_tool_response_and_log_carry_no_details(caplog):
    from unifi_network_mcp.tools import hotspot

    cm = ConnectionManager(HOST, "admin", "secret", port=PORT, ssl_fingerprint=EXPECTED.hex())
    with patch("aiohttp.TCPConnector", _StalePinConnector):
        session = cm._new_session()
    cm.controller = Controller(Configuration(session, HOST, username="admin", password="secret", port=PORT))
    cm.ensure_connected = AsyncMock(return_value=True)
    try:
        with patch.object(hotspot, "hotspot_manager", HotspotManager(cm)), caplog.at_level(logging.DEBUG):
            result = await hotspot.list_vouchers()
    finally:
        await session.close()

    assert result["success"] is False
    assert "UNIFI_NETWORK_SSL_FINGERPRINT" in result["error"]
    for marker in DETAIL_MARKERS:
        assert marker not in result["error"]
        assert marker not in _rendered(caplog)


@pytest.mark.asyncio
async def test_api_key_legacy_session_tool_response_and_log_carry_no_details(monkeypatch, caplog):
    """The key-only legacy session ``_initialize_key`` retains carries the middleware too.

    The capability probe succeeds over a faked transport, then the retained
    session's real connector fails the way a stale pin does once the console
    certificate changes.
    """
    from unifi_core.auth import UniFiAuth
    from unifi_core.network.managers.network_manager import NetworkManager
    from unifi_network_mcp.tools import network

    monkeypatch.setenv("UNIFI_CONTROLLER_TYPE", "proxy")
    cm = ConnectionManager(
        HOST, "", "", port=PORT, ssl_fingerprint=EXPECTED.hex(), auth=UniFiAuth(api_key="synthetic-key")
    )

    async def probe(session, method, url, **kwargs):
        response = AsyncMock()
        response.status = 200
        response.json.return_value = {"meta": {"rc": "ok"}, "data": []}
        response.__aenter__.return_value = response
        response.__aexit__.return_value = None
        return response

    with (
        patch("aiohttp.client.TCPConnector", _StalePinConnector),
        patch("aiohttp.ClientSession._request", new=probe),
    ):
        assert await cm.initialize() is True
    assert cm._key_mode and cm.controller is not None
    try:
        with patch.object(network, "network_manager", NetworkManager(cm)), caplog.at_level(logging.DEBUG):
            result = await network.list_networks()
    finally:
        await cm.cleanup()

    assert result["success"] is False
    assert "UNIFI_NETWORK_SSL_FINGERPRINT" in result["error"]
    for marker in DETAIL_MARKERS:
        assert marker not in result["error"]
        assert marker not in _rendered(caplog)
