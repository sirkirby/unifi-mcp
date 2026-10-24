"""Tests for the shared config_helpers module."""

import pytest
from unifi_core.config_helpers import parse_config_bool


class TestParseConfigBool:
    """Tests for parse_config_bool."""

    @pytest.mark.parametrize(
        ("value", "default", "expected"),
        [
            ("true", False, True),
            ("false", False, False),
            ("1", False, True),
            ("0", False, False),
            ("yes", False, True),
            ("no", False, False),
            ("on", False, True),
            ("off", False, False),
            (True, False, True),
            (False, True, False),
            (None, False, False),
            (None, True, True),
            ("TRUE", False, True),
            ("True", False, True),
            ("YES", False, True),
            ("  true  ", False, True),
            ("  false  ", False, False),
            (1, False, True),
            (0, False, False),
        ],
    )
    def test_parse_config_bool(self, value, default, expected):
        assert parse_config_bool(value, default=default) is expected
