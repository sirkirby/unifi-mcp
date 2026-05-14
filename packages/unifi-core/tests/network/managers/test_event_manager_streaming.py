"""Network EventManager websocket + subscriber tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.event_manager import EventManager


def _make_manager_with_mock_cm() -> EventManager:
    cm = MagicMock()
    cm.controller = MagicMock()
    cm.controller.start_websocket = AsyncMock()
    cm.controller.messages = MagicMock()
    cm.controller.messages.subscribe = MagicMock(return_value=MagicMock())
    return EventManager(cm)


def test_event_manager_initializes_buffer() -> None:
    mgr = _make_manager_with_mock_cm()
    assert mgr.buffer_size == 0


def test_add_subscriber_returns_unsub() -> None:
    mgr = _make_manager_with_mock_cm()
    received: list[dict] = []
    unsub = mgr.add_subscriber(received.append)
    assert callable(unsub)
    # Simulate an event flowing through the manager's internal _on_ws_event
    mgr._on_ws_event({"id": "e1", "key": "EVT_LU_Connected"})
    assert len(received) == 1
    assert received[0]["id"] == "e1"
    unsub()
    mgr._on_ws_event({"id": "e2"})
    assert len(received) == 1  # unsubscribed; no new events


def test_event_buffered_and_fanned_out() -> None:
    mgr = _make_manager_with_mock_cm()
    received_a: list[dict] = []
    received_b: list[dict] = []
    mgr.add_subscriber(received_a.append)
    mgr.add_subscriber(received_b.append)
    mgr._on_ws_event({"id": "e1", "key": "EVT_LU_Connected"})
    assert mgr.buffer_size == 1
    assert len(received_a) == 1
    assert len(received_b) == 1
    assert received_a[0]["id"] == "e1"
    assert received_b[0]["id"] == "e1"


def test_subscriber_callback_exception_does_not_break_others() -> None:
    mgr = _make_manager_with_mock_cm()

    def boom(_evt: dict) -> None:
        raise RuntimeError("oops")

    received: list[dict] = []
    mgr.add_subscriber(boom)
    mgr.add_subscriber(received.append)
    # Must not raise
    mgr._on_ws_event({"id": "e1", "key": "EVT_LU_Connected"})
    assert len(received) == 1
    assert received[0]["id"] == "e1"


def test_get_recent_from_buffer_returns_buffered() -> None:
    mgr = _make_manager_with_mock_cm()
    mgr._on_ws_event({"id": "e1", "key": "EVT_LU_Connected"})
    mgr._on_ws_event({"id": "e2", "key": "EVT_LU_Disconnected"})
    out = mgr.get_recent_from_buffer()
    assert len(out) == 2
    filtered = mgr.get_recent_from_buffer(event_type="EVT_LU_Connected")
    assert len(filtered) == 1
    assert filtered[0]["id"] == "e1"


@pytest.mark.asyncio
async def test_start_listening_calls_controller_start_websocket() -> None:
    mgr = _make_manager_with_mock_cm()
    await mgr.start_listening()
    mgr._cm.controller.start_websocket.assert_awaited_once()
    # subscribe was called to register _on_ws_event handler
    mgr._cm.controller.messages.subscribe.assert_called_once()


@pytest.mark.asyncio
async def test_stop_listening_unsubscribes() -> None:
    mgr = _make_manager_with_mock_cm()
    sentinel_unsub = MagicMock()
    mgr._ws_unsub = sentinel_unsub
    await mgr.stop_listening()
    sentinel_unsub.assert_called_once()
    assert mgr._ws_unsub is None
