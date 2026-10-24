"""Assertions shared by the table-driven model conversion examples."""


def assert_fields(result, expected):
    """Check only named fields, preserving boolean and None identity assertions."""
    for key, value in expected.items():
        actual = result[key] if isinstance(result, dict) else getattr(result, key)
        if value is None or isinstance(value, bool):
            assert actual is value, key
        else:
            assert actual == value, key
