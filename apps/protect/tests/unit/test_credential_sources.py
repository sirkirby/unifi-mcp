"""Protect takes its API key only from the loaded config, never from the raw environment."""

import logging
import os
import uuid

import pytest
from omegaconf import OmegaConf

from unifi_protect_mcp import runtime


@pytest.fixture
def raw_keys(monkeypatch):
    """Both API key variables set to a synthetic marker made for this run."""
    marker = f"key-{uuid.uuid4().hex[:8]}"
    for var in ("UNIFI_API_KEY", "UNIFI_PROTECT_API_KEY"):
        monkeypatch.setenv(var, marker)
    for var in ("UNIFI_SSL_FINGERPRINT", "UNIFI_PROTECT_SSL_FINGERPRINT", "UNIFI_PROTECT_API_SSL_FINGERPRINT"):
        monkeypatch.delenv(var, raising=False)
    return marker


def _use_config(monkeypatch, api_key: str) -> None:
    unifi = {
        "host": "console.invalid",
        "username": "",
        "password": "",
        "port": 443,
        "site": "default",
        "verify_ssl": False,
        "ssl_fingerprint": "",
        "api_ssl_fingerprint": "",
        "api_key": api_key,
    }
    cfg = OmegaConf.create({"unifi": unifi})
    monkeypatch.setattr(runtime, "get_config", lambda: cfg)


@pytest.mark.parametrize("configured", ["", "configured-key"])
def test_auth_takes_the_api_key_only_from_config(raw_keys, monkeypatch, configured):
    _use_config(monkeypatch, configured)
    assert runtime.get_auth.__wrapped__().has_api_key is bool(configured)


@pytest.mark.parametrize("configured", ["", "configured-key"])
def test_connection_manager_takes_the_api_key_only_from_config(raw_keys, monkeypatch, configured):
    _use_config(monkeypatch, configured)
    manager = runtime.get_connection_manager.__wrapped__()
    assert manager._api_key == (configured or None)


def test_another_host_gets_no_shared_credential(monkeypatch, caplog):
    """The real bundled config, a Protect host that is not UNIFI_HOST, and only shared credentials."""
    for name in [n for n in os.environ if n.startswith("UNIFI_") or n == "CONFIG_PATH"]:
        monkeypatch.delenv(name, raising=False)
    run = uuid.uuid4().hex[:8]
    shared = {"UNIFI_USERNAME": f"user-{run}", "UNIFI_PASSWORD": f"pw-{run}", "UNIFI_API_KEY": f"key-{run}"}
    for var, value in {**shared, "UNIFI_HOST": "gateway.invalid", "UNIFI_PROTECT_HOST": "other.invalid"}.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(runtime, "get_config", runtime.get_config.__wrapped__)

    with caplog.at_level(logging.DEBUG):
        auth = runtime.get_auth.__wrapped__()
        manager = runtime.get_connection_manager.__wrapped__()

    assert auth.has_api_key is False
    assert (manager.host, manager.username, manager.password) == ("other.invalid", "", "")
    assert manager._api_key is None
    assert not any(value in caplog.text for value in shared.values())
