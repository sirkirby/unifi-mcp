"""A failed certificate check on the startup login never reaches the connection error or a log.

The aiohttp error names the console host and port and, for a pin mismatch, both
fingerprints. The manager replaces it with fixed guidance naming this server's
own variable; this drives a real login whose connector fails the way a stale pin
does.
"""

import logging

import aiohttp
import pytest

from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager

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
async def test_connection_error_and_log_carry_no_details(monkeypatch, caplog):
    monkeypatch.setattr(aiohttp, "TCPConnector", _StalePinConnector)
    cm = InnerSpaceConnectionManager(
        HOST, "admin", "secret", port=PORT, ssl_fingerprint=EXPECTED.hex(), tls_env_prefix="INNERSPACE"
    )
    with caplog.at_level(logging.DEBUG):
        connected = await cm.initialize()
    await cm.close()

    assert connected is False
    assert "UNIFI_INNERSPACE_SSL_FINGERPRINT" in cm.last_connection_error
    for marker in DETAIL_MARKERS:
        assert marker not in cm.last_connection_error
        assert marker not in _rendered(caplog)
