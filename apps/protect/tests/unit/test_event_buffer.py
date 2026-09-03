"""Tests for EventBuffer ring buffer."""

import time

from unifi_core.protect.managers.event_manager import EventBuffer

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestEventBufferInit:
    def test_defaults(self):
        buf = EventBuffer()
        assert len(buf) == 0
        assert buf._buffer.maxlen == 100
        assert buf._ttl == 300

    def test_custom_params(self):
        buf = EventBuffer(max_size=50, ttl_seconds=60)
        assert buf._buffer.maxlen == 50
        assert buf._ttl == 60


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------


class TestEventBufferAdd:
    def test_add_single(self):
        buf = EventBuffer()
        buf.add({"type": "motion", "camera_id": "cam-001"})
        assert len(buf) == 1

    def test_add_stamps_buffered_at(self):
        buf = EventBuffer()
        event = {"type": "motion"}
        buf.add(event)
        assert "_buffered_at" in event
        assert isinstance(event["_buffered_at"], float)

    def test_add_multiple(self):
        buf = EventBuffer()
        for i in range(5):
            buf.add({"type": "motion", "index": i})
        assert len(buf) == 5


# ---------------------------------------------------------------------------
# Max size / ring behavior
# ---------------------------------------------------------------------------


class TestEventBufferMaxSize:
    def test_overflow_drops_oldest(self):
        buf = EventBuffer(max_size=3)
        for i in range(5):
            buf.add({"index": i})
        assert len(buf) == 3
        # The buffer should contain the last 3 events (indices 2, 3, 4)
        indices = [e["index"] for e in buf._buffer]
        assert indices == [2, 3, 4]


# ---------------------------------------------------------------------------
# get_recent - no filters
# ---------------------------------------------------------------------------


class TestEventBufferGetRecent:
    def test_empty_buffer(self):
        buf = EventBuffer()
        assert buf.get_recent() == []

    def test_returns_newest_first(self):
        buf = EventBuffer()
        buf.add({"type": "motion", "index": 0})
        buf.add({"type": "motion", "index": 1})
        buf.add({"type": "motion", "index": 2})
        results = buf.get_recent()
        assert [r["index"] for r in results] == [2, 1, 0]

    def test_with_limit(self):
        buf = EventBuffer()
        for i in range(10):
            buf.add({"type": "motion", "index": i})
        results = buf.get_recent(limit=3)
        assert len(results) == 3
        assert results[0]["index"] == 9  # newest first

    def test_limit_zero_returns_empty(self):
        """An explicit limit=0 means zero results, not unlimited."""
        buf = EventBuffer()
        for i in range(10):
            buf.add({"type": "motion", "index": i})
        assert buf.get_recent(limit=0) == []


# ---------------------------------------------------------------------------
# get_recent - filters
# ---------------------------------------------------------------------------


class TestEventBufferFilters:
    def test_filter_by_event_type(self):
        buf = EventBuffer()
        buf.add({"type": "motion", "camera_id": "cam-001"})
        buf.add({"type": "smartDetectZone", "camera_id": "cam-001"})
        buf.add({"type": "ring", "camera_id": "cam-002"})
        results = buf.get_recent(event_type="motion")
        assert len(results) == 1
        assert results[0]["type"] == "motion"

    def test_filter_by_camera_id(self):
        buf = EventBuffer()
        buf.add({"type": "motion", "camera_id": "cam-001"})
        buf.add({"type": "motion", "camera_id": "cam-002"})
        buf.add({"type": "motion", "camera_id": "cam-001"})
        results = buf.get_recent(camera_id="cam-001")
        assert len(results) == 2
        assert all(r["camera_id"] == "cam-001" for r in results)

    def test_filter_by_min_confidence(self):
        buf = EventBuffer()
        buf.add({"type": "smartDetectZone", "score": 90})
        buf.add({"type": "smartDetectZone", "score": 40})
        buf.add({"type": "smartDetectZone", "score": 70})
        results = buf.get_recent(min_confidence=50)
        assert len(results) == 2
        assert all(r["score"] >= 50 for r in results)

    def test_combined_filters(self):
        buf = EventBuffer()
        buf.add({"type": "smartDetectZone", "camera_id": "cam-001", "score": 90})
        buf.add({"type": "smartDetectZone", "camera_id": "cam-002", "score": 80})
        buf.add({"type": "motion", "camera_id": "cam-001", "score": 70})
        buf.add({"type": "smartDetectZone", "camera_id": "cam-001", "score": 30})
        results = buf.get_recent(event_type="smartDetectZone", camera_id="cam-001", min_confidence=50)
        assert len(results) == 1
        assert results[0]["score"] == 90

    def test_min_confidence_defaults_to_score_field(self):
        """Events missing 'score' field default to 100 (pass any filter)."""
        buf = EventBuffer()
        buf.add({"type": "motion"})  # no score field
        results = buf.get_recent(min_confidence=50)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# TTL expiration
# ---------------------------------------------------------------------------


class TestEventBufferTTL:
    def test_expired_events_excluded(self):
        buf = EventBuffer(ttl_seconds=10)
        old_event = {"type": "motion", "_buffered_at": time.time() - 20}
        buf._buffer.append(old_event)  # bypass add() to set custom timestamp
        buf.add({"type": "motion"})  # fresh event
        results = buf.get_recent()
        assert len(results) == 1  # only the fresh event

    def test_all_expired(self):
        buf = EventBuffer(ttl_seconds=1)
        buf.add({"type": "motion"})
        # Manually age the event
        buf._buffer[0]["_buffered_at"] = time.time() - 5
        results = buf.get_recent()
        assert len(results) == 0

    def test_mixed_fresh_and_expired(self):
        buf = EventBuffer(ttl_seconds=10)
        # Add an expired event directly
        buf._buffer.append({"type": "motion", "index": 0, "_buffered_at": time.time() - 20})
        # Add fresh events
        buf.add({"type": "motion", "index": 1})
        buf.add({"type": "motion", "index": 2})
        results = buf.get_recent()
        assert len(results) == 2
        assert results[0]["index"] == 2
        assert results[1]["index"] == 1


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


class TestEventBufferClear:
    def test_clear(self):
        buf = EventBuffer()
        for i in range(5):
            buf.add({"index": i})
        assert len(buf) == 5
        buf.clear()
        assert len(buf) == 0
        assert buf.get_recent() == []
