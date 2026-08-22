"""The Access event serializer must understand what the controller sends.

`insights/system_log/search` returns a shape the serializer was never written
for: `event_type` not `type`, `published` (epoch ms) not `timestamp`, and the
actor/door/credential nested under `metadata` rather than as `*_id` keys. Every
one of those mapped to None and `exclude_none=True` dropped it, so a caller got
`{"id": "", "result": "SUCCESS"}` and nothing else - no time, no door, no actor,
no event type.

The payload below mirrors a real controller response; identifiers and
timestamps are synthetic.
"""

from unifi_core.access.models.events import event_from_controller

RAW_SYSTEM_LOG_EVENT = {
    "id": "",
    "log_key": "access.device.update",
    "event_type": "access.device.update",
    "message": "Updated Device Configuration",
    "published": 1787054408829,
    "result": "SUCCESS",
    "metadata": {
        "actor": {"id": "actor-uuid", "type": "user", "display_name": "Test Actor"},
        "device": {
            "id": "device-uuid",
            "type": "UVC G6 Pro Entry",
            "display_name": "Test Reader",
            "alternate_id": "AABBCCDDEEFF",
            "alternate_name": "mac",
        },
    },
}


def test_event_type_comes_from_event_type_key() -> None:
    assert event_from_controller(RAW_SYSTEM_LOG_EVENT).type == "access.device.update"


def test_timestamp_comes_from_published_epoch_millis() -> None:
    ts = event_from_controller(RAW_SYSTEM_LOG_EVENT).timestamp
    assert ts is not None, "published was dropped, so every row is timeless"
    assert ts.startswith("2026-08-"), ts


def test_actor_is_surfaced_as_the_user() -> None:
    assert event_from_controller(RAW_SYSTEM_LOG_EVENT).user_id == "actor-uuid"


def test_message_is_preserved() -> None:
    """The human-readable summary is the single most useful field and was
    being discarded outright."""
    assert event_from_controller(RAW_SYSTEM_LOG_EVENT).message == "Updated Device Configuration"


def test_a_serialized_row_is_not_empty() -> None:
    """The whole-row regression: model_dump(exclude_none=True) used to leave
    exactly {"id": "", "result": "SUCCESS"}."""
    dumped = event_from_controller(RAW_SYSTEM_LOG_EVENT).model_dump(exclude_none=True)
    assert set(dumped) - {"id", "result"}, f"row still carries nothing useful: {dumped}"


def test_legacy_websocket_shape_still_maps() -> None:
    """The websocket/legacy shape uses the original key names; supporting the
    system-log shape must not break it."""
    legacy = {
        "id": "evt-1",
        "type": "access.door.unlock",
        "timestamp": "2026-08-18T12:00:00Z",
        "door_id": "door-1",
        "user_id": "user-1",
        "result": "GRANTED",
    }
    event = event_from_controller(legacy)
    assert event.id == "evt-1"
    assert event.type == "access.door.unlock"
    assert event.door_id == "door-1"
    assert event.user_id == "user-1"


# A real `topic: unlocks` record - the door history the tool exists to serve.
# Identifiers, names and timestamps are synthetic; shape and keys mirror the controller.
RAW_DOOR_UNLOCK = {
    "id": "",
    "log_key": "access.door.unlock",
    "event_type": "access.door.unlock",
    "message": "Access Granted (Face)",
    "published": 1787054400000,
    "result": "ACCESS",
    "metadata": {
        "actor": {"id": "person-uuid", "type": "user", "display_name": "Test Person"},
        "authentication": {
            "id": "auth-id",
            "type": "authentication",
            "display_name": "FACE",
            "credential_provider": "face",
        },
        "door": {"id": "door-uuid", "type": "door", "display_name": "Test Door"},
    },
}

RAW_DOOR_STATUS = {
    "id": "",
    "log_key": "access.dps.status.update",
    "event_type": "access.dps.status.update",
    "message": "Door status - Opened",
    "published": 1787054402000,
    "result": "SUCCESS",
    "metadata": {"actor": {"id": "hub-id", "type": "UA-Hub-Door-Mini", "display_name": "Test Door"}},
}


def test_a_door_unlock_serializes_with_everything_a_caller_needs() -> None:
    event = event_from_controller(RAW_DOOR_UNLOCK)
    assert event.type == "access.door.unlock"
    assert event.message == "Access Granted (Face)"
    assert event.result == "ACCESS"
    assert event.user_id == "person-uuid"
    assert event.door_id == "door-uuid"
    assert event.timestamp is not None and event.timestamp.startswith("2026-08-")


def test_a_door_open_close_record_serializes() -> None:
    event = event_from_controller(RAW_DOOR_STATUS)
    assert event.type == "access.dps.status.update"
    assert event.message == "Door status - Opened"
    assert event.timestamp is not None


# --- metadata attribution ----------------------------------------------------
#
# The metadata sub-objects are typed, and the type matters: `actor` is whoever
# or whatever caused the event, which for a door-status record is the door hub,
# not a person. Reading the id without checking the type presents a device as
# the user and a reader as the door.


def test_a_device_actor_is_not_reported_as_a_user() -> None:
    """`access.dps.status.update` is raised by the hub. Attributing it to a
    person invents a user who did nothing, and the GraphQL `user` edge then
    resolves to null against a non-existent id."""
    assert event_from_controller(RAW_DOOR_STATUS).user_id is None


def test_a_reader_is_not_reported_as_a_door() -> None:
    """A `UVC G6 Pro Entry` reader has its own device UUID. Feeding it back as
    `door_id` to access_list_events or a door lookup matches nothing."""
    assert event_from_controller(RAW_SYSTEM_LOG_EVENT).door_id is None


def test_a_real_door_is_still_read() -> None:
    assert event_from_controller(RAW_DOOR_UNLOCK).door_id == "door-uuid"


def test_a_real_user_actor_is_still_read() -> None:
    assert event_from_controller(RAW_DOOR_UNLOCK).user_id == "person-uuid"
