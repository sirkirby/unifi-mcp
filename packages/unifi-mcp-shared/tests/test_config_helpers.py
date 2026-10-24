"""Tests for the shared config_helpers module."""

import pytest
from unifi_core.config_helpers import parse_config_bool


class TestParseConfigBool:
    """Tests for parse_config_bool."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("true", True),
            ("false", False),
            ("1", True),
            ("0", False),
            ("yes", True),
            ("no", False),
            ("on", True),
            ("off", False),
            (True, True),
            (False, False),
            (None, False),
            ("TRUE", True),
            ("True", True),
            ("YES", True),
            ("  true  ", True),
            ("  false  ", False),
            (1, True),
            (0, False),
        ],
    )
    def test_parse_config_bool(self, value, expected):
        # The keyword is omitted on purpose: these rows pin the declared default.
        assert parse_config_bool(value) is expected

    def test_explicit_default_applies_to_none(self):
        assert parse_config_bool(None, default=True) is True
