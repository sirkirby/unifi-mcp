"""Tests for EventManager.search_detections (detection-search endpoint)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_cm():
    cm = MagicMock()
    cm.client.api_request = AsyncMock()
    return cm


def _make_manager(mock_cm):
    from unifi_core.protect.managers.event_manager import EventManager

    return EventManager(mock_cm)


class TestSearchDetections:
    @pytest.mark.asyncio
    async def test_repeats_labels_param(self, mock_cm):
        mock_cm.client.api_request.return_value = {"events": []}

        await _make_manager(mock_cm).search_detections(
            labels=["vehicleType:truck", "color:black"],
            limit=50,
            order="desc",
            exclude_motion=True,
        )

        mock_cm.client.api_request.assert_awaited_once()
        args, kwargs = mock_cm.client.api_request.await_args
        assert args[0] == "detection-search"
        assert kwargs["method"] == "get"

        params = kwargs["params"]
        # Must be a list of (key, value) tuples so aiohttp repeats the key.
        assert isinstance(params, list)
        for key, value in params:
            assert isinstance(key, str)
            assert isinstance(value, str)

        label_values = [value for key, value in params if key == "labels"]
        assert label_values == ["vehicleType:truck", "color:black"]
        assert ("excludeMotion", "true") in params
        assert ("limit", "50") in params
        assert ("orderDirection", "DESC") in params

    @pytest.mark.asyncio
    async def test_exclude_motion_false_and_asc_order(self, mock_cm):
        mock_cm.client.api_request.return_value = {"events": []}

        await _make_manager(mock_cm).search_detections(
            labels=["color:black"],
            limit=10,
            order="asc",
            exclude_motion=False,
        )

        params = mock_cm.client.api_request.await_args.kwargs["params"]
        assert ("excludeMotion", "false") in params
        assert ("orderDirection", "ASC") in params

    @pytest.mark.asyncio
    async def test_min_confidence_appended(self, mock_cm):
        mock_cm.client.api_request.return_value = {"events": []}

        await _make_manager(mock_cm).search_detections(
            labels=["color:black"],
            limit=50,
            order="desc",
            exclude_motion=True,
            min_confidence=70,
        )

        params = mock_cm.client.api_request.await_args.kwargs["params"]
        assert ("minConfidence", "70") in params

    @pytest.mark.asyncio
    async def test_min_confidence_zero_is_accepted(self, mock_cm):
        mock_cm.client.api_request.return_value = {"events": []}

        await _make_manager(mock_cm).search_detections(
            labels=["color:black"],
            limit=50,
            order="desc",
            exclude_motion=True,
            min_confidence=0,
        )

        params = mock_cm.client.api_request.await_args.kwargs["params"]
        assert ("minConfidence", "0") in params

    @pytest.mark.asyncio
    async def test_start_end_serialized_as_epoch_millis(self, mock_cm):
        from datetime import datetime, timezone

        mock_cm.client.api_request.return_value = {"events": []}

        await _make_manager(mock_cm).search_detections(
            labels=["color:black"],
            limit=50,
            order="desc",
            exclude_motion=True,
            start=datetime(2026, 5, 28, 7, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 6, 4, 13, 51, 59, 999000, tzinfo=timezone.utc),
        )

        params = mock_cm.client.api_request.await_args.kwargs["params"]
        # detection-search wants epoch-millis (captured live from the Find Anything UI).
        assert ("start", "1779951600000") in params
        assert ("end", "1780581119999") in params

    @pytest.mark.asyncio
    async def test_optional_filters_omitted_by_default(self, mock_cm):
        mock_cm.client.api_request.return_value = {"events": []}

        await _make_manager(mock_cm).search_detections(
            labels=["color:black"],
            limit=50,
            order="desc",
            exclude_motion=True,
        )

        keys = [key for key, _ in mock_cm.client.api_request.await_args.kwargs["params"]]
        assert "minConfidence" not in keys
        assert "start" not in keys
        assert "end" not in keys

    @pytest.mark.asyncio
    async def test_rejects_min_confidence_out_of_range(self, mock_cm):
        with pytest.raises(ValueError):
            await _make_manager(mock_cm).search_detections(
                labels=["color:black"],
                limit=50,
                order="desc",
                exclude_motion=True,
                min_confidence=150,
            )

    @pytest.mark.asyncio
    async def test_coalesces_events_into_detections(self, mock_cm):
        mock_cm.client.api_request.return_value = {
            "events": [
                {"id": "d1", "type": "smartDetectZone", "smartDetectTypes": ["vehicle"]},
                {"id": "d2", "type": "smartDetectZone"},
            ]
        }

        result = await _make_manager(mock_cm).search_detections(
            labels=["vehicleType:truck"],
            limit=50,
            order="desc",
            exclude_motion=True,
        )

        assert result["count"] == 2
        assert len(result["detections"]) == 2
        assert result["detections"][0].id == "d1"
        assert result["detections"][1].id == "d2"
        # detection-search returns camelCase smartDetectTypes; it must survive coalescing.
        assert result["detections"][0].smart_detect_types == ["vehicle"]
        assert result["detections"][1].smart_detect_types == []

    @pytest.mark.asyncio
    async def test_non_dict_envelope_yields_empty(self, mock_cm):
        mock_cm.client.api_request.return_value = [{"id": "x", "type": "smartDetectZone"}]

        result = await _make_manager(mock_cm).search_detections(
            labels=["color:black"],
            limit=10,
            order="desc",
            exclude_motion=True,
        )

        assert result == {"detections": [], "count": 0}

    @pytest.mark.asyncio
    async def test_missing_events_key_yields_empty(self, mock_cm):
        mock_cm.client.api_request.return_value = {}

        result = await _make_manager(mock_cm).search_detections(
            labels=["color:black"],
            limit=10,
            order="desc",
            exclude_motion=True,
        )

        assert result == {"detections": [], "count": 0}

    @pytest.mark.asyncio
    async def test_accepts_all_allowed_prefixes(self, mock_cm):
        mock_cm.client.api_request.return_value = {"events": []}
        allowed = [
            "vehicleType:truck",
            "color:black",
            "smartDetectType:vehicle",
            "eventType:motion",
            "groupType:vehicle",
            "camera:cam1",
            "zone:z1",
            "line:l1",
            "loiterZone:lz1",
            "doorAccess:granted",
        ]

        await _make_manager(mock_cm).search_detections(
            labels=allowed,
            limit=50,
            order="desc",
            exclude_motion=True,
        )

        params = mock_cm.client.api_request.await_args.kwargs["params"]
        label_values = [value for key, value in params if key == "labels"]
        assert label_values == allowed

    @pytest.mark.asyncio
    async def test_rejects_invalid_label_prefix(self, mock_cm):
        with pytest.raises(ValueError):
            await _make_manager(mock_cm).search_detections(
                labels=["bogusPrefix:value"],
                limit=50,
                order="desc",
                exclude_motion=True,
            )

    @pytest.mark.asyncio
    async def test_rejects_label_without_prefix(self, mock_cm):
        with pytest.raises(ValueError):
            await _make_manager(mock_cm).search_detections(
                labels=["truck"],
                limit=50,
                order="desc",
                exclude_motion=True,
            )

    @pytest.mark.asyncio
    async def test_rejects_empty_labels(self, mock_cm):
        with pytest.raises(ValueError):
            await _make_manager(mock_cm).search_detections(
                labels=[],
                limit=50,
                order="desc",
                exclude_motion=True,
            )

    @pytest.mark.asyncio
    async def test_rejects_limit_too_low(self, mock_cm):
        with pytest.raises(ValueError):
            await _make_manager(mock_cm).search_detections(
                labels=["color:black"],
                limit=0,
                order="desc",
                exclude_motion=True,
            )

    @pytest.mark.asyncio
    async def test_rejects_limit_too_high(self, mock_cm):
        with pytest.raises(ValueError):
            await _make_manager(mock_cm).search_detections(
                labels=["color:black"],
                limit=1001,
                order="desc",
                exclude_motion=True,
            )

    @pytest.mark.asyncio
    async def test_rejects_invalid_order(self, mock_cm):
        with pytest.raises(ValueError):
            await _make_manager(mock_cm).search_detections(
                labels=["color:black"],
                limit=50,
                order="sideways",
                exclude_motion=True,
            )


class TestGetDetectionSearchLabels:
    @pytest.mark.asyncio
    async def test_requests_labels_endpoint(self, mock_cm):
        mock_cm.client.api_request.return_value = {}

        await _make_manager(mock_cm).get_detection_search_labels()

        mock_cm.client.api_request.assert_awaited_once()
        args, kwargs = mock_cm.client.api_request.await_args
        assert args[0] == "detection-search/labels"
        assert kwargs["method"] == "get"

    @pytest.mark.asyncio
    async def test_returns_serialized_vocabulary(self, mock_cm):
        from unifi_core.protect.models.detection_search import from_controller

        raw = {
            "colors": [{"label": "Black", "value": "color:black"}],
            "vehicleTypes": [{"label": "Truck", "value": "vehicleType:truck"}],
        }
        mock_cm.client.api_request.return_value = raw

        result = await _make_manager(mock_cm).get_detection_search_labels()

        assert result == from_controller(raw).model_dump(exclude_none=True)
        assert result["colors"] == [{"label": "Black", "value": "color:black"}]
        assert result["vehicle_types"] == [{"label": "Truck", "value": "vehicleType:truck"}]

    @pytest.mark.asyncio
    async def test_non_dict_response_yields_empty_groups(self, mock_cm):
        mock_cm.client.api_request.return_value = ["unexpected"]

        result = await _make_manager(mock_cm).get_detection_search_labels()

        assert result["colors"] == []
        assert result["vehicle_types"] == []
