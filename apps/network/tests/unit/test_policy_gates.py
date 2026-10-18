"""Startup scan of UNIFI_POLICY_* names against the gates this server's manifest registers."""

import logging
import os
import re
from pathlib import Path

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


_PERMISSIONS_DOC = Path(__file__).resolve().parents[2] / "docs" / "permissions.md"
_ROW = re.compile(r"^\| `(?P<category>[a-z_]+)` \| (?P<create>[^|]+) \| (?P<update>[^|]+) \| (?P<delete>[^|]+) \|$")


def _documented_gates() -> set[tuple[str, str]]:
    gates = set()
    for line in _PERMISSIONS_DOC.read_text().splitlines():
        row = _ROW.match(line.strip())
        if not row:
            continue
        for action in ("create", "update", "delete"):
            cell = row.group(action).strip()
            if cell != "—":
                expected = f"`UNIFI_POLICY_NETWORK_{row.group('category').upper()}_{action.upper()}`"
                assert cell == expected, f"{row.group('category')} {action}: {cell} should be {expected}"
                gates.add((row.group("category"), action))
    return gates


def test_permissions_doc_lists_every_gate_the_manifest_registers():
    registered = {
        (NETWORK_CATEGORY_MAP.get(category, category), action)
        for category, action in policy_gates()
        if action != "read"
    }
    documented = _documented_gates()

    assert sorted(registered - documented) == [], "gated in the manifest but missing from docs/permissions.md"
    assert sorted(documented - registered) == [], "listed in docs/permissions.md but no tool gates on it"
