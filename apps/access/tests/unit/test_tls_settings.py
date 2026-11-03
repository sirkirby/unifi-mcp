"""TLS settings reach the connection manager at startup: the pin, the warning and the refusal of a bad pin."""

import logging

import pytest

from unifi_access_mcp import runtime

GOOD = "AB" * 32
BAD = "hunter2-not-a-fingerprint"
VARIABLES = (
    "UNIFI_SSL_FINGERPRINT",
    "UNIFI_ACCESS_SSL_FINGERPRINT",
    "UNIFI_ACCESS_API_SSL_FINGERPRINT",
    "UNIFI_API_SSL_FINGERPRINT",
)


@pytest.fixture
def startup(monkeypatch, caplog):
    """Build the manager as the server does at startup, past the process-wide cache."""
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    logger = logging.getLogger("test-tls-startup")
    monkeypatch.setattr(runtime, "logger", logger)
    caplog.set_level(logging.DEBUG, logger=logger.name)
    return runtime.get_connection_manager.__wrapped__


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_warns_once_when_nothing_checks_the_controller(startup, caplog):
    manager = startup()
    assert manager.ssl_fingerprint is None
    [warning] = _warnings(caplog)
    assert "UNIFI_SSL_FINGERPRINT" in warning
    assert "UNIFI_ACCESS_SSL_FINGERPRINT" in warning
    assert "\n" not in warning


def test_shared_pin_reaches_the_manager(startup, caplog, monkeypatch):
    monkeypatch.setenv("UNIFI_SSL_FINGERPRINT", GOOD)
    manager = startup()
    assert manager.ssl_fingerprint == GOOD
    assert manager.tls_env_prefix == "ACCESS"
    assert _warnings(caplog) == []


def test_server_pin_beats_the_shared_one(startup, monkeypatch):
    monkeypatch.setenv("UNIFI_SSL_FINGERPRINT", GOOD)
    monkeypatch.setenv("UNIFI_ACCESS_SSL_FINGERPRINT", "CD" * 32)
    assert startup().ssl_fingerprint == "CD" * 32


@pytest.mark.parametrize("variable", ["UNIFI_SSL_FINGERPRINT", "UNIFI_ACCESS_SSL_FINGERPRINT"])
def test_malformed_pin_stops_startup_without_echoing_it(startup, caplog, capsys, monkeypatch, variable):
    monkeypatch.setenv(variable, BAD)
    with pytest.raises(SystemExit) as excinfo:
        startup()
    assert excinfo.value.code == 2
    assert "SSL_FINGERPRINT" in caplog.text
    captured = capsys.readouterr()
    for text in (caplog.text, captured.out, captured.err):
        assert BAD not in text


def test_loading_config_does_not_log_the_pin(caplog, monkeypatch):
    """Those overrides are logged at debug level, and a mistaken paste may be a secret."""
    from unifi_access_mcp.bootstrap import load_config

    monkeypatch.setenv("UNIFI_ACCESS_SSL_FINGERPRINT", BAD)
    with caplog.at_level(logging.DEBUG):
        load_config()
    assert BAD not in caplog.text


def test_each_port_gets_its_own_pin(startup, caplog, monkeypatch):
    monkeypatch.setenv("UNIFI_ACCESS_SSL_FINGERPRINT", GOOD)
    monkeypatch.setenv("UNIFI_ACCESS_API_SSL_FINGERPRINT", "CD" * 32)
    manager = startup()
    assert manager.ssl_fingerprint == GOOD
    assert manager.api_ssl_fingerprint == "CD" * 32
    assert _warnings(caplog) == []


def test_pinning_only_the_developer_port_does_not_warn(startup, caplog, monkeypatch):
    """The unpinned path is refused rather than left unchecked, so "nothing is checked" would be wrong."""
    monkeypatch.setenv("UNIFI_ACCESS_API_SSL_FINGERPRINT", GOOD)
    assert startup().api_ssl_fingerprint == GOOD
    assert _warnings(caplog) == []


def test_blank_developer_pin_still_warns(startup, caplog, monkeypatch):
    """Blank counts as unset, so nothing is checked and the warning has to fire."""
    monkeypatch.setenv("UNIFI_ACCESS_API_SSL_FINGERPRINT", "   ")
    startup()
    assert len(_warnings(caplog)) == 1


def test_shared_pin_does_not_reach_the_developer_port(startup, monkeypatch):
    """That port presents a different certificate, so the shared pin could never match it."""
    monkeypatch.setenv("UNIFI_SSL_FINGERPRINT", GOOD)
    assert startup().api_ssl_fingerprint is None


def test_malformed_developer_pin_stops_startup_without_echoing_it(startup, caplog, capsys, monkeypatch):
    monkeypatch.setenv("UNIFI_ACCESS_API_SSL_FINGERPRINT", BAD)
    with pytest.raises(SystemExit) as excinfo:
        startup()
    assert excinfo.value.code == 2
    assert "UNIFI_ACCESS_API_SSL_FINGERPRINT" in caplog.text
    captured = capsys.readouterr()
    for text in (caplog.text, captured.out, captured.err):
        assert BAD not in text
