"""Tests for the forget client functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import AiounifiException, ResponseError

from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError

_UNSET = object()


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
    def _controller(
        mock_connection, *, before=True, after=False, stat_user_served=True, forget_error=None, user_table=_UNSET
    ):
        """Answer the per-MAC lookup with the record before and after the forget command."""
        state = {"known": before, "forgotten": False}
        record = {"_id": "u1", "mac": "aa:bb:cc:dd:ee:ff"}

        async def request(api_request, return_raw=False):
            if api_request.path.startswith("/stat/user/"):
                if not stat_user_served:
                    raise ResponseError("Call https://h/proxy/network/api/s/default/stat/user/x received 404 Not Found")
                if state["known"]:
                    return [record]
                raise AiounifiException({"meta": {"rc": "error", "msg": "api.err.UnknownUser"}, "data": []})
            if api_request.path == "/rest/user":
                if user_table is not _UNSET and state["forgotten"]:
                    return user_table
                return [record] if state["known"] else []
            if api_request.path == "/cmd/stamgr":
                if forget_error:
                    raise forget_error
                state["known"] = after
                state["forgotten"] = True
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

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "user_table",
        [None, {"data": []}, ["not-a-record"]],
        ids=["empty-body", "mapping", "non-record-rows"],
    )
    async def test_an_unreadable_user_table_never_confirms_the_forget(
        self, client_manager, mock_connection, user_table
    ):
        """A no-op forget must not read as confirmed because the readback could not be parsed."""
        self._controller(mock_connection, stat_user_served=False, after=True, user_table=user_table)

        with pytest.raises(UniFiOperationError, match="could not be determined"):
            await client_manager.forget_client("AA:BB:CC:DD:EE:FF")

    @pytest.mark.asyncio
    async def test_a_capped_user_table_without_the_client_never_confirms_the_forget(
        self, client_manager, mock_connection
    ):
        from unifi_core.network.managers.client_manager import REST_USER_ROW_CAP

        others = [{"mac": f"02:00:00:{i >> 8 & 255:02x}:{i & 255:02x}:00"} for i in range(REST_USER_ROW_CAP)]
        self._controller(mock_connection, stat_user_served=False, after=True, user_table=others)

        with pytest.raises(UniFiOperationError, match="row cap"):
            await client_manager.forget_client("AA:BB:CC:DD:EE:FF")
