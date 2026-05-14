from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiError,
    UniFiPermissionError,
    UniFiRateLimitError,
)


def test_exception_hierarchy():
    assert issubclass(UniFiAuthError, UniFiError)
    assert issubclass(UniFiConnectionError, UniFiError)
    assert issubclass(UniFiRateLimitError, UniFiError)
    assert issubclass(UniFiPermissionError, UniFiError)


def test_exception_message():
    err = UniFiAuthError("Invalid credentials")
    assert str(err) == "Invalid credentials"
