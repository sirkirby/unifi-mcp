"""Startup scan of UNIFI_POLICY_* names against the gates this server's manifest registers."""

import logging
import os

import pytest

from unifi_core.policy_gate import check_unknown_policy_env_vars
from unifi_protect_mcp.categories import PROTECT_CATEGORY_MAP, policy_gates


@pytest.fixture(autouse=True)
def _clear_policy_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("UNIFI_POLICY_"):
            monkeypatch.delenv(key)


def test_manifest_gates_use_the_shorthand_category():
    assert ("camera", "update") in policy_gates()


def test_shorthand_category_in_env_var_warns_and_names_the_config_key(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_PROTECT_CAMERA_UPDATE", "true")
    monkeypatch.setenv("UNIFI_POLICY_PROTECT_CAMERAS_UPDATE", "true")
    logger = logging.getLogger("test_policy_gates")

    with caplog.at_level(logging.WARNING, logger="test_policy_gates"):
        unknown = check_unknown_policy_env_vars("protect", logger, policy_gates(), PROTECT_CATEGORY_MAP)

    assert unknown == ["UNIFI_POLICY_PROTECT_CAMERA_UPDATE"]
    assert "UNIFI_POLICY_PROTECT_CAMERAS_UPDATE" in caplog.text
