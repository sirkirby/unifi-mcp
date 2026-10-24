"""Tests for the shared validators module."""

import pytest
from unifi_core.validators import ResourceValidator, create_response


class TestResourceValidator:
    """Tests for the ResourceValidator class."""

    @pytest.mark.parametrize(
        ("schema", "resource_name", "payload", "expected_error"),
        [
            (
                {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                "TestResource",
                {},
                "TestResource validation error",
            ),
            (
                {"type": "object", "properties": {"count": {"type": "integer"}}},
                "Widget",
                {"count": "not_a_number"},
                "Widget validation error",
            ),
        ],
    )
    def test_invalid_params(self, schema, resource_name, payload, expected_error):
        validator = ResourceValidator(schema, resource_name)
        is_valid, error, params = validator.validate(payload)
        assert is_valid is False
        assert expected_error in error
        assert params is None

    def test_extra_properties_allowed_by_default(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        validator = ResourceValidator(schema, "Loose")
        is_valid, _, params = validator.validate({"name": "test", "extra": "ok"})
        assert is_valid is True

    def test_validate_does_not_inject_defaults(self):
        """validate() must never fill missing fields from schema defaults.

        Update tools omit fields to mean "leave unchanged" — injecting defaults
        would silently overwrite existing resource state.
        """
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "enabled": {"type": "boolean", "default": True},
                "schedule": {"type": "object", "default": {"mode": "ALWAYS"}},
            },
        }
        validator = ResourceValidator(schema, "Thing")
        is_valid, _, params = validator.validate({"name": "partial update"})
        assert is_valid is True
        assert params == {"name": "partial update"}
        assert "enabled" not in params
        assert "schedule" not in params


class TestValidateAndApplyDefaults:
    """Tests for the opt-in create-path defaults helper."""

    def test_does_not_overwrite_provided_values(self):
        schema = {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "default": True},
                "action": {"type": "string", "default": "BLOCK"},
            },
        }
        validator = ResourceValidator(schema, "Policy")
        _, _, params = validator.validate_and_apply_defaults({"enabled": False, "action": "ALLOW"})
        assert params == {"enabled": False, "action": "ALLOW"}

    def test_properties_without_defaults_stay_absent(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "optional_no_default": {"type": "string"},
                "with_default": {"type": "string", "default": "x"},
            },
        }
        validator = ResourceValidator(schema, "Policy")
        _, _, params = validator.validate_and_apply_defaults({"name": "n"})
        assert "optional_no_default" not in params
        assert params["with_default"] == "x"

    def test_validation_failure_returns_none(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "enabled": {"type": "boolean", "default": True},
            },
            "required": ["name"],
        }
        validator = ResourceValidator(schema, "Policy")
        is_valid, error, params = validator.validate_and_apply_defaults({})
        assert is_valid is False
        assert "Policy validation error" in error
        assert params is None


class TestCreateResponse:
    """Tests for the create_response helper."""

    @pytest.mark.parametrize(
        ("success", "kwargs", "expected"),
        [
            (True, {"data": {"key": "value"}}, {"success": True, "data": {"key": "value"}}),
            (True, {"data": "abc123"}, {"success": True, "id": "abc123"}),
            (True, {}, {"success": True}),
            (False, {"error": "Something went wrong"}, {"success": False, "error": "Something went wrong"}),
            (False, {}, {"success": False}),
        ],
    )
    def test_create_response(self, success, kwargs, expected):
        assert create_response(success, **kwargs) == expected
