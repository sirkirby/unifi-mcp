"""Protect takes its API key only from the loaded config, never from the raw environment."""

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
