"""A failed certificate check on the Integration API paths never exposes its details.

``aiohttp.ServerFingerprintMismatch`` names the controller host and port and both
fingerprints. The DPI and firewall managers must turn it into fixed guidance before
it reaches their logs, the tool logs (which carry ``exc_info``) or the MCP response.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from unifi_core.tls import CertificateVerificationError

HOST = "198.51.100.7"
PORT = 8443
EXPECTED = b"\xaa" * 32
RECEIVED = b"\xbb" * 32
DETAIL_MARKERS = [
    HOST,
    str(PORT),
    EXPECTED.hex(),
    RECEIVED.hex(),
    EXPECTED.hex().upper(),
    RECEIVED.hex().upper(),
    repr(EXPECTED),
    repr(RECEIVED),
]


def _mismatch() -> aiohttp.ServerFingerprintMismatch:
    return aiohttp.ServerFingerprintMismatch(EXPECTED, RECEIVED, HOST, PORT)


def test_markers_would_catch_the_raw_error():
    text = str(_mismatch())
    assert any(marker in text for marker in DETAIL_MARKERS)


def _connection():
    conn = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    conn.host = HOST
    conn.port = PORT
    conn.site = "default"
    conn.ssl = aiohttp.Fingerprint(EXPECTED)
    conn.get_cached = MagicMock(return_value=None)
    return conn


def _auth(session):
    auth = MagicMock()
    auth.has_api_key = True
    auth.get_api_key_session = AsyncMock(return_value=session)
    return auth


def _failing_session(method_name: str):
    session = MagicMock()
    setattr(session, method_name, MagicMock(side_effect=_mismatch()))
    session.close = AsyncMock()
    return session


def _rendered(caplog) -> str:
    formatter = logging.Formatter("%(message)s")
    return "\n".join(formatter.format(record) for record in caplog.records)


def _assert_safe(error: BaseException) -> None:
    assert isinstance(error, CertificateVerificationError)
    assert "ServerFingerprintMismatch" in str(error)
    assert "UNIFI_NETWORK_SSL_FINGERPRINT" in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    for marker in DETAIL_MARKERS:
        assert marker not in str(error)


def _assert_absent(text: str) -> None:
    for marker in DETAIL_MARKERS:
        assert marker not in text


class TestDpi:
    @pytest.fixture
    def manager(self):
        from unifi_core.network.managers.dpi_manager import DpiManager

        session = _failing_session("get")
        manager = DpiManager(_connection(), _auth(session))
        manager.session = session
        return manager

    @pytest.mark.asyncio
    async def test_manager_raises_and_logs_fixed_text(self, manager, caplog):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(CertificateVerificationError) as excinfo:
                await manager._request_integration_api("/v1/dpi/applications")
        _assert_safe(excinfo.value)
        assert caplog.records
        _assert_absent(_rendered(caplog))
        manager.session.close.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", ["list_dpi_applications", "list_dpi_categories"])
    async def test_tool_log_and_response_carry_no_details(self, manager, caplog, tool_name):
        from unifi_network_mcp.tools import dpi

        with patch.object(dpi, "dpi_manager", manager), caplog.at_level(logging.DEBUG):
            result = await getattr(dpi, tool_name)()

        assert result["success"] is False
        assert "UNIFI_NETWORK_SSL_FINGERPRINT" in result["error"]
        _assert_absent(result["error"])
        assert any(record.exc_info for record in caplog.records)
        _assert_absent(_rendered(caplog))


class TestFirewall:
    @pytest.fixture
    def manager(self):
        from unifi_core.network.managers.firewall_manager import FirewallManager

        session = _failing_session("request")
        manager = FirewallManager(_connection(), _auth(session))
        manager.session = session
        return manager

    @pytest.mark.asyncio
    async def test_manager_raises_fixed_text(self, manager, caplog):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(CertificateVerificationError) as excinfo:
                await manager._request_integration_api("get", "/v1/sites")
        _assert_safe(excinfo.value)
        _assert_absent(_rendered(caplog))
        manager.session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_other_errors_still_propagate_unchanged(self, manager):
        manager.session.request.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            await manager._request_integration_api("get", "/v1/sites")
        manager.session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ordering_tool_log_and_response_carry_no_details(self, manager, caplog):
        from unifi_network_mcp.tools import firewall

        with patch.object(firewall, "firewall_manager", manager), caplog.at_level(logging.DEBUG):
            result = await firewall.get_firewall_policy_ordering("zone-src", "zone-dst")

        assert result["success"] is False
        assert "UNIFI_NETWORK_SSL_FINGERPRINT" in result["error"]
        _assert_absent(result["error"])
        assert any(record.exc_info for record in caplog.records)
        _assert_absent(_rendered(caplog))

    @pytest.mark.asyncio
    async def test_reorder_tool_log_and_response_carry_no_details(self, manager, caplog):
        from unifi_network_mcp.tools import firewall

        ordering = {"beforeSystemDefined": ["policy-a"], "afterSystemDefined": []}
        with patch.object(firewall, "firewall_manager", manager), caplog.at_level(logging.DEBUG):
            result = await firewall.reorder_firewall_policies("zone-src", "zone-dst", ordering, confirm=True)

        assert result["success"] is False
        assert "UNIFI_NETWORK_SSL_FINGERPRINT" in result["error"]
        _assert_absent(result["error"])
        _assert_absent(_rendered(caplog))
