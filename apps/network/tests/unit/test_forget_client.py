"""Tests for the forget client functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import AiounifiException, ResponseError

from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError


class TestForgetClient:
    """Tests for ClientManager.forget_client."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        conn.controller = MagicMock()
        conn.controller.clients = MagicMock()
        conn.controller.clients.update = AsyncMock()
        conn.controller.clients.values = MagicMock(return_value=[])
        conn.controller.clients_all = MagicMock()
        conn.controller.clients_all.update = AsyncMock()
        conn.controller.clients_all.values = MagicMock(return_value=[])
        conn.ensure_connected = AsyncMock(return_value=True)
        return conn

    @pytest.fixture
    def client_manager(self, mock_connection):
        """Create a ClientManager with mocked connection."""
        from unifi_core.network.managers.client_manager import ClientManager

        return ClientManager(mock_connection)

    @staticmethod
    def _controller(mock_connection, *, before=True, after=False, stat_user_served=True, forget_error=None):
        """Answer the per-MAC lookup with the record before and after the forget command."""
        state = {"known": before}
        record = {"_id": "u1", "mac": "aa:bb:cc:dd:ee:ff"}

        async def request(api_request, return_raw=False):
            if api_request.path.startswith("/stat/user/"):
                if not stat_user_served:
                    raise ResponseError("Call https://h/proxy/network/api/s/default/stat/user/x received 404 Not Found")
                if state["known"]:
                    return [record]
                raise AiounifiException({"meta": {"rc": "error", "msg": "api.err.UnknownUser"}, "data": []})
            if api_request.path == "/rest/user":
                return [record] if state["known"] else []
            if api_request.path == "/cmd/stamgr":
                if forget_error:
                    raise forget_error
                state["known"] = after
                return [record] if not after else []
            raise AssertionError(f"unexpected request {api_request.path}")

        mock_connection.request = AsyncMock(side_effect=request)

    @staticmethod
    def _forget_calls(mock_connection):
        return [c[0][0] for c in mock_connection.request.call_args_list if c[0][0].path == "/cmd/stamgr"]

    @pytest.mark.asyncio
    async def test_forget_client_success(self, client_manager, mock_connection):
        """A known client is forgotten and confirmed gone.

        The MAC goes out lowercased, so the lookup and the outgoing command
        agree and the controller receives the same casing it reports.
        """
        self._controller(mock_connection)

        result = await client_manager.forget_client("AA:BB:CC:DD:EE:FF")

        assert result is True
        (call,) = self._forget_calls(mock_connection)
        assert call.method == "post"
        assert call.data == {"macs": ["aa:bb:cc:dd:ee:ff"], "cmd": "forget-sta"}
        mock_connection._invalidate_cache.assert_called_once_with("clients")

    @pytest.mark.asyncio
    async def test_client_without_a_known_record_is_not_found_and_nothing_is_sent(
        self, client_manager, mock_connection
    ):
        """The controller acks forget-sta for any MAC, so a historical-only client must not read as forgotten."""
        self._controller(mock_connection, before=False)

        with pytest.raises(UniFiNotFoundError, match="historical statistics"):
            await client_manager.forget_client("AA:BB:CC:DD:EE:FF")
        assert self._forget_calls(mock_connection) == []

    @pytest.mark.asyncio
    async def test_record_still_listed_after_the_command_is_an_error(self, client_manager, mock_connection):
        self._controller(mock_connection, after=True)

        with pytest.raises(UniFiOperationError, match="still lists"):
            await client_manager.forget_client("AA:BB:CC:DD:EE:FF")

    @pytest.mark.asyncio
    async def test_without_the_per_mac_endpoint_the_user_table_decides(self, client_manager, mock_connection):
        self._controller(mock_connection, stat_user_served=False)

        assert await client_manager.forget_client("AA:BB:CC:DD:EE:FF") is True

    @pytest.mark.asyncio
    async def test_forget_client_api_error(self, client_manager, mock_connection):
        """A failed command propagates."""
        self._controller(mock_connection, forget_error=Exception("API error"))

        with pytest.raises(Exception, match="API error"):
            await client_manager.forget_client("AA:BB:CC:DD:EE:FF")
