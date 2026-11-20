"""Network credentials reach the server only through the shared config loader.

The bundled YAML names Network variables only, so the loader decides which level
each value comes from.
"""

import importlib.resources
import uuid

import pytest
from omegaconf import OmegaConf

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
