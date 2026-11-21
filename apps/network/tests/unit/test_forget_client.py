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
        """Create a ClientManager with mocked connection whose settle waits never sleep."""
        from unifi_core.network.managers.client_manager import ClientManager

        return ClientManager(mock_connection, readback_sleep=AsyncMock())

    @staticmethod
    def _controller(
        mock_connection,
        *,
        before=True,
        after=False,
        stat_user_served=True,
        forget_error=None,
        user_table=_UNSET,
        stale_reads=0,
    ):
        """Answer the per-MAC lookup with the record before and after the forget command.

        ``stale_reads`` per-MAC lookups after the command still answer with the
        record, as a controller does whose read lags its write.
        """
        state = {"known": before, "forgotten": False, "stale": 0}
        record = {"_id": "u1", "mac": "aa:bb:cc:dd:ee:ff"}

        async def request(api_request):
            if api_request.path.startswith("/stat/user/"):
                if not stat_user_served:
                    raise ResponseError("Call https://h/proxy/network/api/s/default/stat/user/x received 404 Not Found")
                if state["stale"]:
                    state["stale"] -= 1
                    return [record]
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
                state["stale"] = stale_reads
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
        from unifi_core.write_verification import READBACK_SETTLE_DELAYS_SECONDS

        self._controller(mock_connection, after=True)

        with pytest.raises(UniFiOperationError, match="still lists") as caught:
            await client_manager.forget_client("AA:BB:CC:DD:EE:FF")
        assert "Re-read the client before retrying" in str(caught.value)
        waits = [call.args[0] for call in client_manager._readback_sleep.await_args_list]
        assert waits == list(READBACK_SETTLE_DELAYS_SECONDS)

    @pytest.mark.asyncio
    async def test_a_record_that_lingers_briefly_after_the_command_is_forgotten(self, client_manager, mock_connection):
        """A read made right after the command can still list the client; a later one decides."""
        self._controller(mock_connection, stale_reads=2)

        assert await client_manager.forget_client("AA:BB:CC:DD:EE:FF") is True
        waits = [call.args[0] for call in client_manager._readback_sleep.await_args_list]
        assert waits == [0.25, 0.5]

    @pytest.mark.asyncio
    async def test_a_forget_confirmed_at_once_reads_back_once(self, client_manager, mock_connection):
        self._controller(mock_connection)

        assert await client_manager.forget_client("AA:BB:CC:DD:EE:FF") is True
        lookups = [c[0][0] for c in mock_connection.request.call_args_list if c[0][0].path.startswith("/stat/user/")]
        assert len(lookups) == 2  # One before the command, one after.
        client_manager._readback_sleep.assert_not_awaited()

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
