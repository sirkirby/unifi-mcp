"""The websocket listener has to receive the events the controller actually sends.

`start_listening` registered handlers keyed `door_open` / `door_close` /
`access_granted` / `access_denied` / `door_alarm`. The client dispatches on
`WebsocketMessage.event`, whose real values are `access.logs.add`,
`access.hw.door_bell`, `access.data.device.remote_unlock`, ... - so every
message fell through to the "Unhandled websocket message type" branch and the
ring buffer stayed empty. Starting the listener was therefore inert: it
connected and buffered nothing.

The message is also a frozen model carrying `event` / `event_object_id` /
`door_id` - it has no `type`, `id`, `user_id` or `timestamp` - so reading those
names off it buffered `{"type": "unknown", "door_id": ""}`, which no
`get_recent` filter can match.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.access.managers.event_manager import EventManager

# The real contract this code has to satisfy.
WebsocketMessage = pytest.importorskip("unifi_access_api.models.websocket").WebsocketMessage


def _manager() -> EventManager:
    cm = MagicMock()
    cm.has_proxy = True
    cm.has_api_client = True
    cm.proxy_request = AsyncMock()
    return EventManager(cm)


@pytest.mark.asyncio
async def test_listener_subscribes_to_every_event_type() -> None:
    """The client supports a `"*"` wildcard. Enumerating invented names means
    every real event is dropped."""
    mgr = _manager()
    await mgr.start_listening()
    handlers = mgr._cm.start_websocket.call_args.args[0]
    assert "*" in handlers, f"no wildcard; only {sorted(handlers)} would ever be delivered"


def test_a_real_message_buffers_with_its_event_name_as_the_type() -> None:
    mgr = _manager()
    mgr._on_event(WebsocketMessage(event="access.logs.add", event_object_id="evt-1", door_id="door-1"))
    recent = mgr.get_recent_from_buffer()
    assert len(recent) == 1
    assert recent[0]["type"] == "access.logs.add", recent[0]
    assert recent[0]["id"] == "evt-1", recent[0]
    assert recent[0]["door_id"] == "door-1", recent[0]


def test_a_buffered_message_is_findable_by_its_real_event_type() -> None:
    """`get_recent(event_type=...)` filters on `type`; with `type` stuck at
    "unknown" no caller could ever retrieve a specific event."""
    mgr = _manager()
    mgr._on_event(WebsocketMessage(event="access.hw.door_bell", event_object_id="evt-2", door_id="door-2"))
    assert len(mgr.get_recent_from_buffer(event_type="access.hw.door_bell")) == 1


def test_a_buffered_message_is_findable_by_door() -> None:
    mgr = _manager()
    mgr._on_event(WebsocketMessage(event="access.logs.add", event_object_id="evt-3", door_id="door-3"))
    assert len(mgr.get_recent_from_buffer(door_id="door-3")) == 1


def test_a_buffered_message_is_not_timeless() -> None:
    """Every buffered row had `timestamp: None`, so nothing downstream could
    order or age them."""
    mgr = _manager()
    mgr._on_event(WebsocketMessage(event="access.logs.add", event_object_id="evt-4", door_id="door-4"))
    assert mgr.get_recent_from_buffer()[0].get("timestamp")


def test_plain_dict_events_still_buffer_unchanged() -> None:
    mgr = _manager()
    mgr._on_event({"id": "evt-5", "type": "door_open", "door_id": "door-5", "timestamp": "2026-08-18T12:00:00Z"})
    recent = mgr.get_recent_from_buffer()
    assert recent[0]["type"] == "door_open"
    assert recent[0]["id"] == "evt-5"


def test_subscribers_receive_the_normalized_shape() -> None:
    mgr = _manager()
    seen: list[dict] = []
    mgr.add_subscriber(seen.append)
    mgr._on_event(WebsocketMessage(event="access.logs.add", event_object_id="evt-6", door_id="door-6"))
    assert seen and seen[0]["type"] == "access.logs.add"


# --- what reaches the buffer --------------------------------------------------


def test_the_data_subpayload_is_not_buffered() -> None:
    """`access_recent_events` and GET /access/recent-events return buffered
    rows unprojected, so carrying the whole model dump would put actor display
    names and credential ids in front of any READ-scoped caller."""
    mgr = _manager()
    mgr._on_event(
        WebsocketMessage(
            event="access.logs.add",
            event_object_id="e1",
            data={"actor": {"display_name": "Test Person", "id": "user-1"}, "credential": {"id": "cred-1"}},
        )
    )
    row = mgr.get_recent_from_buffer()[0]
    assert "data" not in row, row
    assert not any("cred-1" in str(v) for v in row.values()), row


def test_high_rate_telemetry_does_not_evict_real_events() -> None:
    """The wildcard also delivers location/remote-view frames. The ring holds
    100 entries, so a burst would push out a just-occurred door unlock."""
    mgr = _manager()
    mgr._on_event(WebsocketMessage(event="access.door.unlock", event_object_id="unlock-1", door_id="door-1"))
    for i in range(200):
        mgr._on_event(WebsocketMessage(event="access.data.v2.location.update", event_object_id=f"loc-{i}"))
    assert len(mgr.get_recent_from_buffer(event_type="access.door.unlock")) == 1
