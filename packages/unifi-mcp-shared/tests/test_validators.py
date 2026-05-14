"""Tests for the shared validators module."""

from unifi_core.validators import ResourceValidator, create_response


class TestResourceValidator:
    """Tests for the ResourceValidator class."""

    def test_valid_params(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        validator = ResourceValidator(schema, "TestResource")
        is_valid, error, params = validator.validate({"name": "test"})
        assert is_valid is True
        assert error is None
        assert params == {"name": "test"}

    def test_invalid_params_missing_required(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        validator = ResourceValidator(schema, "TestResource")
        is_valid, error, params = validator.validate({})
        assert is_valid is False
        assert "TestResource validation error" in error
        assert params is None

    def test_invalid_params_wrong_type(self):
        schema = {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
        validator = ResourceValidator(schema, "Widget")
        is_valid, error, params = validator.validate({"count": "not_a_number"})
        assert is_valid is False
        assert "Widget validation error" in error

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
        would silently overwrite existing resource state (issue #113 class of bug).
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

    def test_fills_missing_defaults(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "enabled": {"type": "boolean", "default": True},
                "schedule": {"type": "object", "default": {"mode": "ALWAYS"}},
                "action": {"type": "string", "default": "BLOCK"},
            },
            "required": ["name"],
        }
        validator = ResourceValidator(schema, "Policy")
        is_valid, error, params = validator.validate_and_apply_defaults({"name": "new"})
        assert is_valid is True
        assert error is None
        assert params == {
            "name": "new",
            "enabled": True,
            "schedule": {"mode": "ALWAYS"},
            "action": "BLOCK",
        }

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

    def test_success_with_data_dict(self):
        result = create_response(True, data={"key": "value"})
        assert result == {"success": True, "data": {"key": "value"}}

    def test_success_with_string_data(self):
        result = create_response(True, data="abc123")
        assert result == {"success": True, "id": "abc123"}

    def test_success_no_data(self):
        result = create_response(True)
        assert result == {"success": True}

    def test_failure_with_error(self):
        result = create_response(False, error="Something went wrong")
        assert result == {"success": False, "error": "Something went wrong"}

    def test_failure_no_error(self):
        result = create_response(False)
        assert result == {"success": False}
