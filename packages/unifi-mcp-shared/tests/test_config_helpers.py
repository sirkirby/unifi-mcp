"""Tests for the shared config_helpers module."""

from unifi_core.config_helpers import parse_config_bool


class TestParseConfigBool:
    """Tests for parse_config_bool."""

    def test_true_string(self):
        assert parse_config_bool("true") is True

    def test_false_string(self):
        assert parse_config_bool("false") is False

    def test_one_string(self):
        assert parse_config_bool("1") is True

    def test_zero_string(self):
        assert parse_config_bool("0") is False

    def test_yes_string(self):
        assert parse_config_bool("yes") is True

    def test_no_string(self):
        assert parse_config_bool("no") is False

    def test_on_string(self):
        assert parse_config_bool("on") is True

    def test_off_string(self):
        assert parse_config_bool("off") is False

    def test_bool_true(self):
        assert parse_config_bool(True) is True

    def test_bool_false(self):
        assert parse_config_bool(False) is False

    def test_none_default_false(self):
        assert parse_config_bool(None) is False

    def test_none_default_true(self):
        assert parse_config_bool(None, default=True) is True

    def test_case_insensitive(self):
        assert parse_config_bool("TRUE") is True
        assert parse_config_bool("True") is True
        assert parse_config_bool("YES") is True

    def test_whitespace_stripped(self):
        assert parse_config_bool("  true  ") is True
        assert parse_config_bool("  false  ") is False

    def test_integer_truthy(self):
        assert parse_config_bool(1) is True
        assert parse_config_bool(0) is False
