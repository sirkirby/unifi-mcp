"""Tests for UniFiValidatorRegistry — schema/key wiring and gaps."""

from __future__ import annotations

import pathlib
import re

import pytest

from unifi_network_mcp.validator_registry import UniFiValidatorRegistry


TOOLS_DIR = pathlib.Path(__file__).resolve().parents[2] / "src" / "unifi_network_mcp" / "tools"
KEY_RE = re.compile(
    r'UniFiValidatorRegistry\.(?:validate|validate_and_apply_defaults)\(\s*[\"\']([a-z0-9_]+)[\"\']'
)


def _all_referenced_keys() -> set[str]:
    """Scan tools/*.py for every key passed to UniFiValidatorRegistry.validate*."""
    files = list(TOOLS_DIR.glob("*.py"))
    assert len(files) > 10, (
        f"Sanity check failed: TOOLS_DIR={TOOLS_DIR} found {len(files)} files. "
        f"The test was written assuming the network app has many tool modules; "
        f"if you've intentionally restructured, update this assertion."
    )
    keys: set[str] = set()
    for path in files:
        for match in KEY_RE.finditer(path.read_text()):
            keys.add(match.group(1))
    # Some keys are passed via dynamic schema_key = "..." then validate(schema_key, ...).
    # Capture the most common cases used in firewall.py.
    keys |= {"firewall_policy_create", "firewall_policy_v2_create"}
    return keys


def test_every_referenced_key_is_registered():
    """Tools that call validate(<key>, ...) require <key> to exist in the registry.

    Background: the audit for #205 surfaced that ``qos_rule`` and
    ``qos_rule_update`` were referenced by qos.py but never registered,
    silently breaking ``unifi_create_qos_rule`` and ``unifi_update_qos_rule``
    in production for an unknown duration.
    """
    referenced = _all_referenced_keys()
    registered = set(UniFiValidatorRegistry._validators.keys())
    missing = sorted(referenced - registered)
    assert not missing, "Tools reference unregistered validator keys: %s" % missing
