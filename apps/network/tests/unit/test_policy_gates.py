"""Startup scan of UNIFI_POLICY_* names against the gates this server's manifest registers."""

import logging
import os

import pytest

from unifi_core.policy_gate import check_unknown_policy_env_vars
from unifi_network_mcp.categories import NETWORK_CATEGORY_MAP, policy_gates


@pytest.fixture(autouse=True)
def _clear_policy_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("UNIFI_POLICY_"):
            monkeypatch.delenv(key)


def test_manifest_gates_use_the_shorthand_category():
    assert ("client_group", "delete") in policy_gates()


def test_shorthand_category_in_env_var_warns_and_names_the_config_key(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_NETWORK_CLIENT_GROUP_DELETE", "true")
    monkeypatch.setenv("UNIFI_POLICY_NETWORK_CLIENT_GROUPS_DELETE", "true")
    logger = logging.getLogger("test_policy_gates")

    with caplog.at_level(logging.WARNING, logger="test_policy_gates"):
        unknown = check_unknown_policy_env_vars("network", logger, policy_gates(), NETWORK_CATEGORY_MAP)

    assert unknown == ["UNIFI_POLICY_NETWORK_CLIENT_GROUP_DELETE"]
    assert "UNIFI_POLICY_NETWORK_CLIENT_GROUPS_DELETE" in caplog.text
