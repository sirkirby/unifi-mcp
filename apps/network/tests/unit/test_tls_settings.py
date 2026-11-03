"""TLS settings reach the connection manager at startup: the pin, the warning and the refusal of a bad pin."""

import logging

import pytest

from unifi_network_mcp import runtime

GOOD = "AB" * 32
BAD = "hunter2-not-a-fingerprint"
VARIABLES = ("UNIFI_SSL_FINGERPRINT", "UNIFI_NETWORK_SSL_FINGERPRINT")


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
    assert "UNIFI_NETWORK_SSL_FINGERPRINT" in warning
    assert "\n" not in warning


def test_shared_pin_reaches_the_manager(startup, caplog, monkeypatch):
    monkeypatch.setenv("UNIFI_SSL_FINGERPRINT", GOOD)
    manager = startup()
    assert manager.ssl_fingerprint == GOOD
    assert manager.tls_env_prefix == "NETWORK"
    assert _warnings(caplog) == []


def test_server_pin_beats_the_shared_one(startup, monkeypatch):
    monkeypatch.setenv("UNIFI_SSL_FINGERPRINT", GOOD)
    monkeypatch.setenv("UNIFI_NETWORK_SSL_FINGERPRINT", "CD" * 32)
    assert startup().ssl_fingerprint == "CD" * 32


@pytest.mark.parametrize("variable", ["UNIFI_SSL_FINGERPRINT", "UNIFI_NETWORK_SSL_FINGERPRINT"])
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
    from unifi_network_mcp.bootstrap import load_config

    monkeypatch.setenv("UNIFI_NETWORK_SSL_FINGERPRINT", BAD)
    with caplog.at_level(logging.DEBUG):
        load_config()
    assert BAD not in caplog.text
