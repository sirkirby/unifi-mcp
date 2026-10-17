"""A failed certificate check on an ordinary Access request never reaches a tool response or log.

The aiohttp error names the controller host and port and, for a pin mismatch,
both fingerprints. The connection manager's sessions replace it with fixed
guidance before py-unifi-access or the proxy helpers see it; this drives a real
tool over a real session whose connector fails the way a stale pin does.
"""

import logging
from unittest.mock import patch

import aiohttp
import pytest

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.managers.credential_manager import CredentialManager

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
    from unifi_access_mcp.tools import credentials

    cm = AccessConnectionManager(HOST, "admin", "secret", port=PORT, ssl_fingerprint=EXPECTED.hex())
    cm._proxy_session = aiohttp.ClientSession(connector=_StalePinConnector(), middlewares=cm._session_middlewares())
    cm._proxy_available = True
    try:
        with patch.object(credentials, "credential_manager", CredentialManager(cm)), caplog.at_level(logging.DEBUG):
            result = await credentials.access_list_credentials()
    finally:
        await cm._proxy_session.close()

    assert result["success"] is False
    assert "UNIFI_ACCESS_SSL_FINGERPRINT" in result["error"]
    assert any(record.exc_info for record in caplog.records)
    for marker in DETAIL_MARKERS:
        assert marker not in result["error"]
        assert marker not in _rendered(caplog)
