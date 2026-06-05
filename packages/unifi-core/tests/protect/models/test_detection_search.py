"""Tests for the Protect detection-search labels vocabulary model."""

from __future__ import annotations

from unifi_core.protect.models.detection_search import (
    DetectionSearchLabels,
    DetectionSearchLabelValue,
    from_controller,
)


class TestDetectionSearchLabelValue:
    def test_label_value_round_trips(self):
        item = DetectionSearchLabelValue(label="Truck", value="vehicleType:truck")
        assert item.label == "Truck"
        assert item.value == "vehicleType:truck"

    def test_label_value_allows_missing_fields(self):
        item = DetectionSearchLabelValue()
        assert item.label is None
        assert item.value is None


class TestDetectionSearchLabelsFromController:
    def _raw(self):
        return {
            "colors": [
                {"label": "Black", "value": "color:black"},
                {"label": "White", "value": "color:white"},
            ],
            "vehicleTypes": [
                {"label": "Truck", "value": "vehicleType:truck"},
                {"label": "SUV", "value": "vehicleType:suv"},
            ],
            "smartDetectTypes": [
                {"label": "Vehicle", "value": "smartDetectType:vehicle"},
            ],
            "eventTypes": [
                {"label": "Ring", "value": "eventType:ring"},
            ],
            "groupType": [
                {"label": "Known", "value": "groupType:known"},
            ],
            "devices": [
                {"label": "Front Cam", "type": "camera", "value": "camera:abc123"},
            ],
            "doorAccess": [
                {"label": "Granted", "value": "doorAccess:granted"},
            ],
        }

    def test_maps_camelcase_groups_into_typed_snake_case_lists(self):
        labels = from_controller(self._raw())

        assert isinstance(labels, DetectionSearchLabels)
        assert [c.value for c in labels.colors] == ["color:black", "color:white"]
        assert [v.label for v in labels.vehicle_types] == ["Truck", "SUV"]
        assert labels.smart_detect_types[0].value == "smartDetectType:vehicle"
        assert labels.event_types[0].value == "eventType:ring"
        assert labels.group_type[0].value == "groupType:known"
        assert labels.devices[0].value == "camera:abc123"
        assert labels.door_access[0].value == "doorAccess:granted"

    def test_uses_prefixed_label_when_controller_value_is_suffix_only(self):
        labels = from_controller(
            {
                "colors": [{"label": "color:black", "value": "black"}],
                "vehicleTypes": [{"label": "vehicleType:truck", "value": "truck"}],
                "smartDetectTypes": [{"label": "smartDetectType:animal", "value": "animal"}],
                "devices": [{"label": "camera:abc123", "value": "abc123"}],
            }
        )

        assert labels.colors[0].value == "color:black"
        assert labels.vehicle_types[0].value == "vehicleType:truck"
        assert labels.smart_detect_types[0].value == "smartDetectType:animal"
        assert labels.devices[0].value == "camera:abc123"

    def test_items_are_label_value_models(self):
        labels = from_controller(self._raw())
        assert isinstance(labels.colors[0], DetectionSearchLabelValue)
        assert labels.colors[0].label == "Black"

    def test_missing_groups_default_to_empty_lists(self):
        labels = from_controller({"colors": [{"label": "Black", "value": "color:black"}]})

        assert [c.value for c in labels.colors] == ["color:black"]
        assert labels.vehicle_types == []
        assert labels.smart_detect_types == []
        assert labels.event_types == []
        assert labels.group_type == []
        assert labels.devices == []
        assert labels.door_access == []

    def test_non_dict_input_yields_empty_model(self):
        labels = from_controller(None)
        assert labels.colors == []
        assert labels.vehicle_types == []

    def test_ignores_non_list_group_values(self):
        labels = from_controller({"colors": "not-a-list", "vehicleTypes": None})
        assert labels.colors == []
        assert labels.vehicle_types == []

    def test_skips_non_dict_items(self):
        labels = from_controller({"colors": ["not-a-dict", {"label": "Black", "value": "color:black"}]})
        assert [c.value for c in labels.colors] == ["color:black"]

    def test_model_dump_exclude_none_round_trips(self):
        labels = from_controller(self._raw())
        dumped = labels.model_dump(exclude_none=True)

        assert dumped["colors"] == [
            {"label": "Black", "value": "color:black"},
            {"label": "White", "value": "color:white"},
        ]
        assert dumped["vehicle_types"][0] == {"label": "Truck", "value": "vehicleType:truck"}
        # snake_case keys are used in the serialized output
        assert "smart_detect_types" in dumped
        assert "vehicleTypes" not in dumped
