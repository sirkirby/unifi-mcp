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


def test_http_status_reads_aiounifi_message_and_v2_error_body():
    from unifi_core.exceptions import http_status

    assert (
        http_status(RuntimeError("Call https://host/proxy/network/v2/api/site/default/nat received 404 Not Found"))
        == 404
    )
    assert http_status(RuntimeError({"errorCode": 405, "message": "Method Not Allowed"})) == 405
    assert http_status(RuntimeError("Error requesting data from https://host:8443/v2: timeout 404")) is None
    assert http_status(RuntimeError()) is None
