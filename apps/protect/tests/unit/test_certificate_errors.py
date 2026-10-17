"""A failed certificate check on ongoing Protect SDK traffic never reaches a tool response or log.

uiprotect wraps an aiohttp ``ClientError`` as ``NvrError("Error requesting data
from <host>: <error>")``, and a pin mismatch's text carries both fingerprints.
The sessions the connection manager hands uiprotect replace the failure before
uiprotect sees it; this drives a real tool through the real SDK over a session
whose connector fails the way a stale pin does.
"""

import logging
from unittest.mock import patch

import aiohttp
import pytest
from uiprotect import ProtectApiClient

from unifi_core.protect.managers.alarm_facade import AlarmRulesFacade
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

HOST = "198.51.100.7"
PORT = 8443
EXPECTED = b"\xaa" * 32
RECEIVED = b"\xbb" * 32
FINGERPRINT_MARKERS = [EXPECTED.hex(), RECEIVED.hex(), repr(EXPECTED), repr(RECEIVED)]


class _StalePinConnector(aiohttp.TCPConnector):
    async def _create_connection(self, req, traces, timeout):
        raise aiohttp.ServerFingerprintMismatch(EXPECTED, RECEIVED, HOST, PORT)


def _rendered(caplog) -> str:
    formatter = logging.Formatter("%(message)s")
    return "\n".join(formatter.format(record) for record in caplog.records)


@pytest.mark.asyncio
async def test_tool_response_and_log_carry_no_details(caplog):
    from unifi_protect_mcp.tools import alarm

    cm = ProtectConnectionManager(HOST, "admin", "secret", port=PORT, ssl_fingerprint=EXPECTED.hex())
    with patch("aiohttp.TCPConnector", _StalePinConnector):
        options = cm._client_tls_options()
    client = ProtectApiClient(HOST, PORT, "admin", "secret", **options)
    cm._client = client
    cm._initialized = True
    try:
        with (
            patch.object(alarm, "alarm_facade", AlarmRulesFacade.from_connection(cm)),
            caplog.at_level(logging.DEBUG),
        ):
            result = await alarm.protect_alarm_list_profiles()
    finally:
        await client.close_session()
        await client.close_public_api_session()

    assert result["success"] is False
    assert "UNIFI_PROTECT_SSL_FINGERPRINT" in result["error"]
    assert HOST not in result["error"]
    assert str(PORT) not in result["error"]
    assert any(record.exc_info for record in caplog.records)
    # uiprotect's own debug log names the request URL; nothing from the failed
    # check may appear in the response or any log record.
    for marker in FINGERPRINT_MARKERS:
        assert marker not in result["error"]
        assert marker not in _rendered(caplog)
