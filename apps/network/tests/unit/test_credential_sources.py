"""Network credentials reach the server only through the shared config loader.

The bundled YAML names Network variables only, so the loader decides which level
each value comes from.
"""

import importlib.resources
import logging
import os
import uuid

import pytest
from omegaconf import OmegaConf

from unifi_network_mcp import runtime

_KEYS = ("HOST", "USERNAME", "PASSWORD", "PORT", "SITE", "VERIFY_SSL", "CONTROLLER_TYPE", "API_KEY")
_VARS = [f"UNIFI_{p}{k}{s}" for p in ("NETWORK_", "") for k in _KEYS for s in ("", "_FILE", "_COMMAND")]


@pytest.fixture
def shared(monkeypatch):
    """Every shared variable set to a synthetic marker made for this run."""
    for var in (*_VARS, "CONFIG_PATH"):
        monkeypatch.delenv(var, raising=False)
    run = uuid.uuid4().hex[:8]
    values = {
        "UNIFI_HOST": f"shared-{run}.invalid",
        "UNIFI_USERNAME": f"user-{run}",
        "UNIFI_PASSWORD": f"pw-{run}",
        "UNIFI_API_KEY": f"key-{run}",
        "UNIFI_PORT": "8443",
        "UNIFI_SITE": f"site-{run}",
        "UNIFI_VERIFY_SSL": "true",
        "UNIFI_CONTROLLER_TYPE": "proxy",
    }
    for var, value in values.items():
        monkeypatch.setenv(var, value)
    return values


def test_bundled_yaml_reads_no_shared_variable(shared):
    path = importlib.resources.files("unifi_network_mcp.config").joinpath("config.yaml")
    unifi = OmegaConf.to_container(OmegaConf.load(str(path)).unifi, resolve=True)

    assert not {str(v) for v in unifi.values()} & set(shared.values())


def test_shared_variables_alone_still_configure_network(shared):
    from unifi_network_mcp.bootstrap import load_config

    unifi = load_config().unifi

    assert unifi.host == shared["UNIFI_HOST"]
    assert unifi.username == shared["UNIFI_USERNAME"]
    assert unifi.password == shared["UNIFI_PASSWORD"]
    assert unifi.api_key == shared["UNIFI_API_KEY"]
    assert str(unifi.port) == "8443"
    assert unifi.site == shared["UNIFI_SITE"]
    assert unifi.verify_ssl is True
    assert unifi.controller_type == "proxy"


@pytest.mark.parametrize("configured", ["", "configured-key"])
def test_api_key_comes_only_from_config(shared, monkeypatch, configured):
    cfg = OmegaConf.create({"unifi": {"api_key": configured}})
    monkeypatch.setattr(runtime, "get_config", lambda: cfg)

    assert runtime.get_auth.__wrapped__().has_api_key is bool(configured)


def test_another_host_gets_no_shared_credential(monkeypatch, caplog):
    """The real bundled config, a Network host that is not UNIFI_HOST, and only shared credentials."""
    for name in [n for n in os.environ if n.startswith("UNIFI_") or n == "CONFIG_PATH"]:
        monkeypatch.delenv(name, raising=False)
    run = uuid.uuid4().hex[:8]
    shared = {"UNIFI_USERNAME": f"user-{run}", "UNIFI_PASSWORD": f"pw-{run}", "UNIFI_API_KEY": f"key-{run}"}
    for var, value in {**shared, "UNIFI_HOST": "gateway.invalid", "UNIFI_NETWORK_HOST": "other.invalid"}.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(runtime, "get_config", runtime.get_config.__wrapped__)
    # The manager takes its key from get_auth; bypass the cache so it is built from this environment.
    monkeypatch.setattr(runtime, "get_auth", runtime.get_auth.__wrapped__)

    with caplog.at_level(logging.DEBUG):
        auth = runtime.get_auth()
        manager = runtime.get_connection_manager.__wrapped__()

    assert auth.has_api_key is False
    assert (manager.host, manager.username, manager.password) == ("other.invalid", "", "")
    assert manager.has_api_key is False
    assert not any(value in caplog.text for value in shared.values())
