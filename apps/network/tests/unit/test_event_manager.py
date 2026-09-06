"""Tests for the EventManager class.

Tests both the v2 system-log API (modern controllers) and the legacy
/stat/event API (older controllers).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestEventManagerV2:
    """Tests for the EventManager using the v2 system-log API."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        return conn

    @pytest.fixture
    def event_manager(self, mock_connection):
        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(mock_connection)
        mgr._use_v2 = True  # Force v2 mode
        return mgr

    @pytest.mark.asyncio
    async def test_get_events_returns_list(self, event_manager, mock_connection):
        mock_connection.request.return_value = [
            {
                "data": [
                    {"id": "evt1", "event": "CLIENT_CONNECTED_WIRED", "category": "CLIENT_DEVICES"},
                    {"id": "evt2", "event": "CLIENT_DISCONNECTED_WIRELESS", "category": "CLIENT_DEVICES"},
                ],
                "total_element_count": 2,
            }
        ]
        events = await event_manager.get_events(within=24, limit=100)
        assert len(events) == 2
        assert events[0]["id"] == "evt1"

    @pytest.mark.asyncio
    async def test_get_events_with_exact_event_key(self, event_manager, mock_connection):
        mock_connection.request.return_value = [{"data": [], "total_element_count": 0}]
        await event_manager.get_events(event_type="CLIENT_CONNECTED_WIRELESS_2")
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["keys"] == ["CLIENT_CONNECTED_WIRELESS_2"]
        assert api_request.data["searchText"] == ""

    @pytest.mark.asyncio
    async def test_get_events_paginates_past_v2_page_size_cap(self, event_manager, mock_connection):
        first_page = [{"id": f"evt{i}"} for i in range(100)]
        second_page = [{"id": f"evt{i}"} for i in range(100, 150)]
        mock_connection.request.side_effect = [
            [{"data": first_page, "total_page_count": 2}],
            [{"data": second_page, "total_page_count": 2}],
        ]

        events = await event_manager.get_events(limit=150)

        assert len(events) == 150
        requests = [call.args[0] for call in mock_connection.request.call_args_list]
        assert [request.data["pageNumber"] for request in requests] == [0, 1]
        assert all(request.data["pageSize"] == 100 for request in requests)

    @pytest.mark.asyncio
    async def test_get_events_applies_arbitrary_start_across_pages(self, event_manager, mock_connection):
        mock_connection.request.side_effect = [
            [{"data": [{"id": f"evt{i}"} for i in range(100, 110)], "total_page_count": 12}],
            [{"data": [{"id": f"evt{i}"} for i in range(110, 120)], "total_page_count": 12}],
        ]

        events = await event_manager.get_events(limit=10, start=105)

        assert [event["id"] for event in events] == [f"evt{i}" for i in range(105, 115)]
        requests = [call.args[0] for call in mock_connection.request.call_args_list]
        assert [request.data["pageNumber"] for request in requests] == [10, 11]

    @pytest.mark.asyncio
    async def test_get_events_zero_limit_makes_no_request(self, event_manager, mock_connection):
        assert await event_manager.get_events(limit=0) == []
        mock_connection.request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_events_uses_timestamp_range(self, event_manager, mock_connection):
        mock_connection.request.return_value = [{"data": [], "total_element_count": 0}]
        await event_manager.get_events(within=48)
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert "timestampFrom" in api_request.data
        assert "timestampTo" in api_request.data
        assert api_request.data["timestampTo"] > api_request.data["timestampFrom"]

    @pytest.mark.asyncio
    async def test_get_events_handles_error(self, event_manager, mock_connection):
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await event_manager.get_events()

    @pytest.mark.asyncio
    async def test_get_alarms_v2(self, event_manager, mock_connection):
        mock_connection.request.return_value = [
            {
                "data": [
                    {"id": "alm1", "event": "THREAT_DETECTED", "severity": "VERY_HIGH"},
                ],
                "total_element_count": 1,
            }
        ]
        alarms = await event_manager.get_alarms()
        assert len(alarms) == 1
        assert alarms[0]["severity"] == "VERY_HIGH"

    @pytest.mark.asyncio
    async def test_get_alarms_v2_limit(self, event_manager, mock_connection):
        mock_data = [{"id": f"alm{i}"} for i in range(200)]
        mock_connection.request.return_value = [{"data": mock_data, "total_element_count": 200}]
        alarms = await event_manager.get_alarms(limit=50)
        assert len(alarms) == 50


class TestEventManagerLegacy:
    """Tests for the EventManager using the legacy /stat/event API."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        return conn

    @pytest.fixture
    def event_manager(self, mock_connection):
        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(mock_connection)
        mgr._use_v2 = False  # Force legacy mode
        return mgr

    @pytest.mark.asyncio
    async def test_get_events_returns_list(self, event_manager, mock_connection):
        mock_events = [
            {"_id": "evt1", "msg": "Client connected", "time": 1700000000},
            {"_id": "evt2", "msg": "Client disconnected", "time": 1700000100},
        ]
        mock_connection.request.return_value = mock_events
        events = await event_manager.get_events(within=24, limit=100)
        assert len(events) == 2
        assert events[0]["_id"] == "evt1"

    @pytest.mark.asyncio
    async def test_get_events_with_type_filter(self, event_manager, mock_connection):
        mock_connection.request.return_value = []
        await event_manager.get_events(event_type="EVT_SW_Connected")
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["type"] == "EVT_SW_Connected"

    @pytest.mark.asyncio
    async def test_get_events_respects_limit(self, event_manager, mock_connection):
        mock_connection.request.return_value = []
        await event_manager.get_events(limit=5000)
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["_limit"] == 3000

    @pytest.mark.asyncio
    async def test_get_events_handles_dict_response(self, event_manager, mock_connection):
        mock_connection.request.return_value = {"data": [{"_id": "evt1"}], "meta": {"rc": "ok"}}
        events = await event_manager.get_events()
        assert len(events) == 1
        assert events[0]["_id"] == "evt1"

    @pytest.mark.asyncio
    async def test_get_events_handles_error(self, event_manager, mock_connection):
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await event_manager.get_events()

    @pytest.mark.asyncio
    async def test_get_alarms_returns_list(self, event_manager, mock_connection):
        mock_alarms = [
            {"_id": "alm1", "msg": "High CPU usage", "severity": "warning"},
            {"_id": "alm2", "msg": "Device offline", "severity": "critical"},
        ]
        mock_connection.request.return_value = mock_alarms
        alarms = await event_manager.get_alarms()
        assert len(alarms) == 2

    @pytest.mark.asyncio
    async def test_get_alarms_archived_parameter(self, event_manager, mock_connection):
        mock_connection.request.return_value = []
        await event_manager.get_alarms(archived=True)
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert "archived=true" in api_request.path

    @pytest.mark.asyncio
    async def test_get_alarms_limit(self, event_manager, mock_connection):
        mock_alarms = [{"_id": f"alm{i}"} for i in range(200)]
        mock_connection.request.return_value = mock_alarms
        alarms = await event_manager.get_alarms(limit=50)
        assert len(alarms) == 50


class TestEventManagerCommon:
    """Tests for shared EventManager functionality."""

    @pytest.fixture
    def mock_connection(self):
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        return conn

    @pytest.fixture
    def event_manager(self, mock_connection):
        from unifi_core.network.managers.event_manager import EventManager

        return EventManager(mock_connection)

    @pytest.mark.asyncio
    async def test_get_event_types_returns_observed_exact_keys(self, event_manager, mock_connection):
        event_manager._use_v2 = True
        mock_connection.request.return_value = [
            {
                "data": [
                    {"key": "CLIENT_DISCONNECTED_WIRELESS_2"},
                    {"key": "CLIENT_CONNECTED_WIRELESS_2"},
                    {"key": "CLIENT_DISCONNECTED_WIRELESS_2"},
                    {"key": None},
                ]
            }
        ]

        event_types = await event_manager.get_event_types()

        assert [event_type["key"] for event_type in event_types] == [
            "CLIENT_CONNECTED_WIRELESS_2",
            "CLIENT_DISCONNECTED_WIRELESS_2",
        ]
        assert event_types[1]["prefix"] == "CLIENT_DISCONNECTED_WIRELESS_2"
        assert event_types[1]["observed_count"] == 2
        assert all("description" in event_type for event_type in event_types)

    def test_get_event_type_prefixes_remains_synchronous_for_compatibility(self, event_manager):
        prefixes = event_manager.get_event_type_prefixes()

        assert any(prefix["prefix"] == "EVT_SW_" for prefix in prefixes)
        assert any(prefix["prefix"] == "EVT_AP_" for prefix in prefixes)

    def test_get_event_categories(self, event_manager):
        categories = event_manager.get_event_categories()
        assert len(categories) > 0
        assert any(c["category"] == "SECURITY" for c in categories)
        assert all("description" in c for c in categories)

    @pytest.mark.asyncio
    async def test_archive_alarm_success(self, event_manager, mock_connection):
        mock_connection.request.return_value = {}
        result = await event_manager.archive_alarm("alarm123")
        assert result is True
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.data["cmd"] == "archive-alarm"

    @pytest.mark.asyncio
    async def test_archive_alarm_failure(self, event_manager, mock_connection):
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await event_manager.archive_alarm("alarm123")

    @pytest.mark.asyncio
    async def test_archive_all_alarms_success(self, event_manager, mock_connection):
        mock_connection.request.return_value = {}
        result = await event_manager.archive_all_alarms()
        assert result is True

    @pytest.mark.asyncio
    async def test_archive_all_alarms_failure(self, event_manager, mock_connection):
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await event_manager.archive_all_alarms()

    @pytest.mark.asyncio
    async def test_auto_detect_v2(self, event_manager, mock_connection):
        """Test that v2 API is detected when system-log/count succeeds."""
        mock_connection.request.return_value = {"count": 100}
        await event_manager._ensure_api_version()
        assert event_manager._use_v2 is True

    @pytest.mark.asyncio
    async def test_auto_detect_legacy(self, event_manager, mock_connection):
        """Test that legacy API is used when system-log/count fails."""
        mock_connection.request.side_effect = Exception("404")
        await event_manager._ensure_api_version()
        assert event_manager._use_v2 is False

    @pytest.mark.asyncio
    async def test_failed_probe_is_logged_with_the_actual_error(self, event_manager, mock_connection, caplog):
        """The probe error must reach the log, or a later 404 is undiagnosable."""
        mock_connection.request.side_effect = Exception("Bad Request: unknown severity LOW")

        with caplog.at_level("WARNING"):
            await event_manager._ensure_api_version()

        assert event_manager._use_v2 is False
        assert "unknown severity LOW" in caplog.text

    @pytest.mark.asyncio
    async def test_failed_probe_is_recorded_for_later_diagnosis(self, event_manager, mock_connection):
        mock_connection.request.side_effect = Exception("Bad Request: unknown severity LOW")
        await event_manager._ensure_api_version()
        assert "unknown severity LOW" in event_manager._v2_probe_error

    @pytest.mark.asyncio
    async def test_successful_probe_records_no_error(self, event_manager, mock_connection):
        mock_connection.request.return_value = {"count": 1}
        await event_manager._ensure_api_version()
        assert event_manager._v2_probe_error is None

    @pytest.mark.asyncio
    async def test_legacy_events_404_after_failed_probe_explains_both(self, event_manager, mock_connection):
        """A 404 from a legacy path we only chose because v2 probing failed is not a bare 404."""
        mock_connection.request.side_effect = [
            Exception("Bad Request: unknown severity LOW"),  # v2 probe
            Exception("received 404 Not Found"),  # legacy /stat/event
        ]

        with pytest.raises(Exception) as exc:
            await event_manager.get_events()

        message = str(exc.value)
        assert "404" in message
        assert "unknown severity LOW" in message, "the v2 probe failure must be surfaced, not swallowed"

    @pytest.mark.asyncio
    async def test_legacy_alarms_404_after_failed_probe_explains_both(self, event_manager, mock_connection):
        mock_connection.request.side_effect = [
            Exception("Bad Request: unknown severity LOW"),  # v2 probe
            Exception("received 404 Not Found"),  # legacy /stat/alarm
        ]

        with pytest.raises(Exception) as exc:
            await event_manager.get_alarms()

        assert "unknown severity LOW" in str(exc.value)

    @pytest.mark.asyncio
    async def test_legacy_failure_on_a_genuinely_old_controller_is_left_alone(self, event_manager, mock_connection):
        """No probe error recorded means legacy was a real choice — do not editorialise."""
        event_manager._use_v2 = False
        event_manager._v2_probe_error = None
        mock_connection.request.side_effect = Exception("connection reset")

        with pytest.raises(Exception) as exc:
            await event_manager.get_events()

        assert "connection reset" in str(exc.value)
        assert "v2 system-log probe" not in str(exc.value)


class TestWebsocketLifecycle:
    """start_listening subscribes, then runs aiounifi's blocking receive loop in
    a background task that reconnects; stop_listening tears both down."""

    @staticmethod
    def _controller(*, fail_first: Exception | None = None):
        import asyncio

        controller = MagicMock()
        controller.started = asyncio.Event()
        controller.block = asyncio.Event()
        calls = {"n": 0}

        controller.closed = asyncio.Event()

        async def _ws():
            calls["n"] += 1
            if fail_first is not None and calls["n"] == 1:
                raise fail_first
            controller.started.set()
            await controller.block.wait()
            controller.closed.set()

        controller.start_websocket = AsyncMock(side_effect=_ws)
        controller.messages.subscribe = MagicMock(return_value=MagicMock(name="unsub"))
        # aiounifi stamps this on every frame it receives; None until the first one.
        controller.connectivity.ws_message_received = None
        return controller

    @staticmethod
    def _frame_received(controller):
        """The peer sent a frame on the open socket (what aiounifi records)."""
        import datetime

        controller.connectivity.ws_message_received = datetime.datetime.now(datetime.UTC)

    @pytest.fixture
    def cm(self):
        cm = MagicMock()
        cm.reconnect_blocked = False
        cm.reconnect_cooldown_active = False
        cm.ensure_connected = AsyncMock(return_value=True)
        cm.reauthenticate = AsyncMock(return_value=True)
        cm.controller = self._controller()
        return cm

    class _Sleeps(list):
        """Recorded backoff delays; ``reached`` is set once ``until`` are recorded."""

        def __init__(self):
            import asyncio

            super().__init__()
            self.until: int | None = None
            self.reached = asyncio.Event()

    @pytest.fixture
    def sleeps(self, monkeypatch):
        """Replace the loop's sleep with a recorder that still yields."""
        import asyncio

        from unifi_core.network.managers import event_manager as em

        recorded = self._Sleeps()
        real_sleep = asyncio.sleep

        async def _sleep(delay):
            recorded.append(delay)
            if recorded.until is not None and len(recorded) >= recorded.until:
                recorded.reached.set()
            await real_sleep(0)

        monkeypatch.setattr(em.asyncio, "sleep", _sleep)
        return recorded

    async def _wait(self, event):
        import asyncio

        await asyncio.wait_for(event.wait(), 1)

    @pytest.mark.asyncio
    async def test_start_subscribes_before_the_socket_and_returns_while_it_blocks(self, cm):
        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(cm)
        await mgr.start_listening()

        assert cm.controller.messages.subscribe.call_count == 1
        assert mgr.is_listening is True
        await self._wait(cm.controller.started)
        assert cm.controller.start_websocket.await_count == 1

        await mgr.stop_listening()
        assert mgr.is_listening is False
        cm.controller.messages.subscribe.return_value.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, cm):
        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(cm)
        await mgr.start_listening()
        await mgr.start_listening()
        await self._wait(cm.controller.started)

        assert cm.controller.messages.subscribe.call_count == 1
        assert cm.controller.start_websocket.await_count == 1
        await mgr.stop_listening()

    @pytest.mark.asyncio
    async def test_stop_when_never_started_is_a_noop(self, cm):
        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(cm)
        await mgr.stop_listening()
        assert mgr.is_listening is False

    @pytest.mark.asyncio
    async def test_loop_reconnects_and_resubscribes_on_a_new_controller(self, cm, sleeps):
        """A reconnect replaces the aiounifi Controller object; the subscription
        must move to the new one."""
        from unifi_core.network.managers.event_manager import EventManager

        first = self._controller(fail_first=RuntimeError("socket closed"))
        second = self._controller()
        cm.controller = first

        async def _ensure():
            if first.start_websocket.await_count:
                cm.controller = second
            return True

        cm.ensure_connected = AsyncMock(side_effect=_ensure)
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(second.started)

        assert first.messages.subscribe.call_count == 1
        assert second.messages.subscribe.call_count == 1
        first.messages.subscribe.return_value.assert_called_once()  # old subscription released
        assert sleeps == [1]
        await mgr.stop_listening()

    @pytest.mark.asyncio
    async def test_backoff_doubles_to_a_cap_while_the_socket_keeps_failing(self, cm, sleeps):
        from unifi_core.network.managers.event_manager import EventManager

        cm.controller.start_websocket = AsyncMock(side_effect=RuntimeError("down"))
        sleeps.until = 8
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(sleeps.reached)
        await mgr.stop_listening()

        assert sleeps[:8] == [1, 2, 4, 8, 16, 32, 60, 60]

    @pytest.mark.asyncio
    async def test_loop_waits_out_the_auth_cooldown_without_touching_the_controller(self, cm, sleeps):
        from unifi_core.network.managers.event_manager import EventManager

        cm.reconnect_cooldown_active = True
        sleeps.until = 3
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(sleeps.reached)
        await mgr.stop_listening()

        cm.ensure_connected.assert_not_awaited()
        cm.controller.start_websocket.assert_not_awaited()
        assert sleeps == sorted(sleeps)

    @pytest.mark.asyncio
    async def test_handshake_401_triggers_reauthentication(self, cm, sleeps):
        import aiohttp

        from unifi_core.network.managers.event_manager import EventManager

        rejected = aiohttp.WSServerHandshakeError(
            request_info=MagicMock(), history=(), status=401, message="Unauthorized"
        )
        cm.controller = self._controller(fail_first=rejected)
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(cm.controller.started)
        await mgr.stop_listening()

        cm.reauthenticate.assert_awaited_once()

    def test_buffer_capacity_comes_from_config(self, cm):
        from unifi_core.network.managers.event_manager import EventManager

        assert EventManager(cm, config={"buffer_size": 5}).buffer_capacity == 5
        assert EventManager(cm).buffer_capacity == 100


class TestWebsocketHealth(TestWebsocketLifecycle):
    """A running task is not an attached socket: the tools need to tell them apart."""

    @pytest.mark.asyncio
    async def test_a_socket_that_never_attaches_is_reported(self, cm, sleeps):
        import aiohttp

        from unifi_core.network.managers.event_manager import EventManager

        cm.controller.start_websocket = AsyncMock(
            side_effect=aiohttp.WSServerHandshakeError(request_info=MagicMock(), history=(), status=404, message="nope")
        )
        sleeps.until = 2
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(sleeps.reached)

        assert mgr.is_listening is True
        assert mgr.attached is False
        assert "WSServerHandshakeError" in mgr.last_error and "404" in mgr.last_error
        await mgr.stop_listening()

    @pytest.mark.asyncio
    async def test_an_attached_socket_clears_the_error(self, cm, sleeps):
        from unifi_core.network.managers.event_manager import EventManager

        cm.controller = self._controller(fail_first=RuntimeError("first"))
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(cm.controller.started)
        self._frame_received(cm.controller)

        assert mgr.attached is True
        assert mgr.last_error is None
        await mgr.stop_listening()

    @pytest.mark.asyncio
    async def test_attached_needs_a_confirmed_open_socket(self, cm):
        """Maintainer probe 1: with the handshake held, the task is alive but no
        socket is open, so ``attached`` must be false; a received frame is the
        confirmation; a closure clears it again for the whole backoff."""
        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(cm.controller.started)  # inside start_websocket, handshake never completed

        assert mgr.is_listening is True
        assert mgr.attached is False
        assert mgr.last_error is None

        self._frame_received(cm.controller)
        assert mgr.attached is True

        cm.controller.block.set()  # normal closure by the peer
        await self._wait(cm.controller.closed)
        assert mgr.attached is False
        await mgr.stop_listening()

    @pytest.mark.asyncio
    async def test_a_frame_from_a_previous_socket_does_not_count(self, cm):
        """A stale timestamp from before this attach is not a confirmation."""
        import datetime

        from unifi_core.network.managers.event_manager import EventManager

        cm.controller.connectivity.ws_message_received = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            hours=1
        )
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(cm.controller.started)

        assert mgr.attached is False
        await mgr.stop_listening()

    @pytest.mark.asyncio
    async def test_loop_retries_once_the_auth_cooldown_has_expired(self, cm, sleeps):
        """Maintainer probe 2: ``reconnect_blocked`` stays latched until a login
        succeeds, but the circuit half-opens on a timer; the listener must let
        the ConnectionManager's time-aware check decide, so one login attempt
        happens after expiry."""
        from unifi_core.network.managers.event_manager import EventManager

        cm.reconnect_blocked = True  # latched from an earlier terminal auth error
        cm.reconnect_cooldown_active = False  # ...but the cool-down has expired
        cm.ensure_connected = AsyncMock(return_value=False)  # the half-open attempt fails
        sleeps.until = 1
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(sleeps.reached)

        cm.ensure_connected.assert_awaited()
        await mgr.stop_listening()

    @pytest.mark.asyncio
    async def test_stop_unsubscribes_even_when_the_caller_is_cancelled(self, cm):
        """Maintainer probe 3: a cancellation aimed at the stopping caller must
        propagate AND the subscription must still be released."""
        import asyncio

        from unifi_core.network.managers.event_manager import EventManager

        unsub = MagicMock(name="unsub")
        cm.controller.messages.subscribe = MagicMock(return_value=unsub)
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(cm.controller.started)
        entered = asyncio.Event()

        async def _shutdown():
            entered.set()
            await mgr.stop_listening()

        outer = asyncio.create_task(_shutdown())
        await self._wait(entered)
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer

        assert outer.cancelled()
        unsub.assert_called_once()
        assert mgr.is_listening is False
        assert mgr.attached is False

    @pytest.mark.asyncio
    async def test_open_reconnect_circuit_is_reported_as_not_attached(self, cm, sleeps):
        from unifi_core.network.managers.event_manager import EventManager

        cm.reconnect_cooldown_active = True
        sleeps.until = 1
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(sleeps.reached)

        assert mgr.attached is False
        assert "circuit" in mgr.last_error
        await mgr.stop_listening()

    @pytest.mark.asyncio
    async def test_persistent_failure_escalates_to_error_once(self, cm, sleeps, caplog):
        import logging

        from unifi_core.network.managers.event_manager import EventManager

        cm.controller.start_websocket = AsyncMock(side_effect=RuntimeError("down"))
        sleeps.until = 9
        mgr = EventManager(cm)
        with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
            await mgr.start_listening()
            await self._wait(sleeps.reached)
            await mgr.stop_listening()

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1 and "has not attached" in errors[0].getMessage()
        assert "down" not in caplog.text or all(
            r.levelno == logging.DEBUG for r in caplog.records if "down" in r.getMessage()
        )

    @pytest.mark.asyncio
    async def test_reauthentication_failure_does_not_kill_the_task(self, cm, sleeps, caplog):
        import logging

        import aiohttp

        from unifi_core.network.managers.event_manager import EventManager

        rejected = aiohttp.WSServerHandshakeError(
            request_info=MagicMock(), history=(), status=401, message="Unauthorized"
        )
        cm.controller.start_websocket = AsyncMock(side_effect=rejected)
        cm.reauthenticate = AsyncMock(side_effect=RuntimeError("login exploded"))
        sleeps.until = 2
        mgr = EventManager(cm)
        with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
            await mgr.start_listening()
            await self._wait(sleeps.reached)

        assert mgr.is_listening is True
        assert any("re-authentication failed" in r.getMessage() for r in caplog.records)
        await mgr.stop_listening()

    @pytest.mark.asyncio
    async def test_a_task_that_dies_is_logged_at_error(self, cm, caplog):
        """Nothing in the loop should escape, but if something does the death
        is logged, not discovered at garbage collection."""
        import asyncio
        import logging

        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(cm)

        async def _boom():
            raise RuntimeError("escaped")

        with caplog.at_level(logging.DEBUG, logger="unifi-network-mcp"):
            mgr._ws_task = asyncio.create_task(_boom())
            mgr._ws_task.add_done_callback(mgr._on_task_done)
            for _ in range(3):
                await asyncio.sleep(0)
            await mgr.stop_listening()

        assert any(r.levelno == logging.ERROR and "RuntimeError" in r.getMessage() for r in caplog.records)

    @staticmethod
    def _closing_socket(cm, outcomes):
        import asyncio

        block = asyncio.Event()

        async def _ws():
            if outcomes:
                outcome = outcomes.pop(0)
                if outcome is not None:
                    raise outcome
                return  # accepted, then closed by the peer without an error
            await block.wait()

        cm.controller.start_websocket = AsyncMock(side_effect=_ws)

    @pytest.mark.asyncio
    async def test_a_stable_attachment_resets_the_backoff(self, cm, sleeps):
        from unifi_core.network.managers.event_manager import EventManager

        clock = {"now": 0.0}

        def _monotonic():
            clock["now"] += 10.0  # every attachment looks long-lived
            return clock["now"]

        self._closing_socket(cm, [RuntimeError("a"), RuntimeError("b"), None, RuntimeError("c")])
        sleeps.until = 4
        mgr = EventManager(cm)
        mgr._clock = _monotonic
        await mgr.start_listening()
        await self._wait(sleeps.reached)
        await mgr.stop_listening()

        assert sleeps[:4] == [1, 2, 1, 2]
        assert cm.controller.messages.subscribe.call_count == 1

    @pytest.mark.asyncio
    async def test_an_immediate_close_keeps_backing_off(self, cm, sleeps):
        """A peer that accepts the socket and closes it at once must not be
        polled every second."""
        from unifi_core.network.managers.event_manager import EventManager

        self._closing_socket(cm, [None, None, None, None])
        sleeps.until = 4
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(sleeps.reached)

        assert sleeps[:4] == [1, 2, 4, 8]
        assert mgr.attached is False
        assert "before it was stable" in mgr.last_error
        await mgr.stop_listening()
        assert mgr.last_error is None

    @pytest.mark.asyncio
    async def test_stop_re_raises_a_cancellation_aimed_at_the_caller(self, cm):
        import asyncio

        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(cm.controller.started)
        entered = asyncio.Event()

        async def _shutdown():
            entered.set()
            await mgr.stop_listening()
            return "completed"

        outer = asyncio.create_task(_shutdown())
        await self._wait(entered)
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer
        assert outer.cancelled()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status,reauth", [(401, True), (403, True), (500, False)])
    async def test_only_rejected_handshakes_reauthenticate(self, cm, sleeps, status, reauth):
        import aiohttp

        from unifi_core.network.managers.event_manager import EventManager

        cm.controller = self._controller(
            fail_first=aiohttp.WSServerHandshakeError(request_info=MagicMock(), history=(), status=status, message="x")
        )
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(cm.controller.started)
        await mgr.stop_listening()

        assert cm.reauthenticate.await_count == (1 if reauth else 0)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", ["not_connected", "no_controller"])
    async def test_connection_gaps_back_off_without_touching_the_socket(self, cm, sleeps, case):
        from unifi_core.network.managers.event_manager import EventManager

        if case == "not_connected":
            cm.ensure_connected = AsyncMock(return_value=False)
        else:
            cm.controller = None
        sleeps.until = 2
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(sleeps.reached)
        await mgr.stop_listening()

        assert sleeps[:2] == [1, 2]

    @pytest.mark.asyncio
    async def test_stop_interrupts_a_backoff_sleep(self, cm, monkeypatch):
        import asyncio

        from unifi_core.network.managers import event_manager as em
        from unifi_core.network.managers.event_manager import EventManager

        cm.controller.start_websocket = AsyncMock(side_effect=RuntimeError("down"))
        sleeping = asyncio.Event()

        async def _sleep(_delay):
            sleeping.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(em.asyncio, "sleep", _sleep)
        mgr = EventManager(cm)
        await mgr.start_listening()
        await self._wait(sleeping)
        await asyncio.wait_for(mgr.stop_listening(), 1)

        assert mgr.is_listening is False

    @pytest.mark.asyncio
    async def test_start_after_stop_is_refused(self, cm):
        """A stopped manager was dropped by its owner; a stale caller must not
        revive it with a discarded connection."""
        from unifi_core.network.managers.event_manager import EventManager

        mgr = EventManager(cm)
        await mgr.start_listening()
        await mgr.stop_listening()
        await mgr.start_listening()

        assert mgr.is_listening is False
