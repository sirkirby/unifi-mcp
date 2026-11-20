"""Access takes its API key only from the loaded config, never from the raw environment."""

import logging
import os
import uuid

import pytest
from omegaconf import OmegaConf

from unifi_access_mcp import runtime
from unifi_mcp_shared import bootstrap as shared_bootstrap


@pytest.fixture
def raw_keys(monkeypatch):
    """Both API key variables set to a synthetic marker made for this run."""
    marker = f"key-{uuid.uuid4().hex[:8]}"
    for var in ("UNIFI_API_KEY", "UNIFI_ACCESS_API_KEY"):
        monkeypatch.setenv(var, marker)
    for var in ("UNIFI_SSL_FINGERPRINT", "UNIFI_ACCESS_SSL_FINGERPRINT", "UNIFI_ACCESS_API_SSL_FINGERPRINT"):
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
    """The real bundled config, a Access host that is not UNIFI_HOST, and only shared credentials."""
    for name in [n for n in os.environ if n.startswith("UNIFI_") or n == "CONFIG_PATH"]:
        monkeypatch.delenv(name, raising=False)
    run = uuid.uuid4().hex[:8]
    shared = {"UNIFI_USERNAME": f"user-{run}", "UNIFI_PASSWORD": f"pw-{run}", "UNIFI_API_KEY": f"key-{run}"}
    for var, value in {**shared, "UNIFI_HOST": "gateway.invalid", "UNIFI_ACCESS_HOST": "other.invalid"}.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(runtime, "get_config", runtime.get_config.__wrapped__)

    with caplog.at_level(logging.DEBUG):
        auth = runtime.get_auth.__wrapped__()
        manager = runtime.get_connection_manager.__wrapped__()

    assert auth.has_api_key is False
    assert (manager.host, manager.username, manager.password) == ("other.invalid", "", "")
    assert manager._api_key is None
    assert not any(value in caplog.text for value in shared.values())


@pytest.mark.parametrize("shared_host", ["gateway.invalid", "other.invalid"], ids=["another-host", "same-host"])
def test_connection_manager_gets_the_cut_credential_warnings(monkeypatch, shared_host):
    """A rejected login names the shared credentials this server ignored, never their values."""
    for name in [n for n in os.environ if n.startswith("UNIFI_") or n == "CONFIG_PATH"]:
        monkeypatch.delenv(name, raising=False)
    run = uuid.uuid4().hex[:8]
    # Every variable counts as the launcher's, as in a real start.
    monkeypatch.setattr(shared_bootstrap, "_TRUSTED_VARS", None)
    monkeypatch.setenv("UNIFI_PASSWORD", f"pw-{run}")
    monkeypatch.setenv("UNIFI_HOST", shared_host)
    monkeypatch.setenv("UNIFI_ACCESS_HOST", "other.invalid")
    monkeypatch.setattr(runtime, "get_config", runtime.get_config.__wrapped__)

    manager = runtime.get_connection_manager.__wrapped__()

    if shared_host == "other.invalid":
        assert manager.auth_failure_hint is None
        return
    assert manager.auth_failure_hint == (
        "UNIFI_PASSWORD is set but not used: the host comes from UNIFI_ACCESS_HOST, which differs from "
        "UNIFI_HOST; set UNIFI_ACCESS_PASSWORD (or its _FILE/_COMMAND form)."
    )


@pytest.mark.asyncio
async def test_a_failed_start_names_the_ignored_shared_credentials(monkeypatch):
    """Shared credentials only, another host: no login is sent and the error names what to set."""
    for name in [n for n in os.environ if n.startswith("UNIFI_") or n == "CONFIG_PATH"]:
        monkeypatch.delenv(name, raising=False)
    run = uuid.uuid4().hex[:8]
    monkeypatch.setattr(shared_bootstrap, "_TRUSTED_VARS", None)
    shared = {"UNIFI_USERNAME": f"user-{run}", "UNIFI_PASSWORD": f"pw-{run}"}
    for var, value in {**shared, "UNIFI_HOST": "gateway.invalid", "UNIFI_ACCESS_HOST": "other.invalid"}.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(runtime, "get_config", runtime.get_config.__wrapped__)
    manager = runtime.get_connection_manager.__wrapped__()

    assert await manager.initialize() is False

    error = manager.last_connection_error
    assert "No UniFi Access credentials are configured" in error
    assert error.endswith(
        "UNIFI_USERNAME is set but not used: the host comes from UNIFI_ACCESS_HOST, which differs from UNIFI_HOST; "
        "set UNIFI_ACCESS_USERNAME. UNIFI_PASSWORD is set but not used: the host comes from UNIFI_ACCESS_HOST, which "
        "differs from UNIFI_HOST; set UNIFI_ACCESS_PASSWORD (or its _FILE/_COMMAND form)."
    )
    assert not any(value in error for value in [*shared.values(), "gateway.invalid", "other.invalid"])
