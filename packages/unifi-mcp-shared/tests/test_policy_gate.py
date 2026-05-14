"""Tests for the policy gate checker and permission mode resolver."""

import os
from unittest.mock import patch

from unifi_core.policy_gate import PolicyGateChecker, resolve_permission_mode


class TestPolicyGateChecker:
    """Tests for 3-level env var policy gate hierarchy."""

    def test_no_gates_set_allows(self):
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(os.environ, {}, clear=True):
            assert checker.check("networks", "update") is True

    def test_global_gate_denies(self):
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(os.environ, {"UNIFI_POLICY_UPDATE": "false"}, clear=True):
            assert checker.check("networks", "update") is False

    def test_global_gate_allows(self):
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(os.environ, {"UNIFI_POLICY_UPDATE": "true"}, clear=True):
            assert checker.check("networks", "update") is True

    def test_server_gate_overrides_global(self):
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(
            os.environ,
            {
                "UNIFI_POLICY_UPDATE": "false",
                "UNIFI_POLICY_NETWORK_UPDATE": "true",
            },
            clear=True,
        ):
            assert checker.check("networks", "update") is True

    def test_category_gate_overrides_server(self):
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(
            os.environ,
            {
                "UNIFI_POLICY_NETWORK_UPDATE": "true",
                "UNIFI_POLICY_NETWORK_NETWORKS_UPDATE": "false",
            },
            clear=True,
        ):
            assert checker.check("networks", "update") is False

    def test_category_gate_overrides_global(self):
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(
            os.environ,
            {
                "UNIFI_POLICY_UPDATE": "false",
                "UNIFI_POLICY_NETWORK_NETWORKS_UPDATE": "true",
            },
            clear=True,
        ):
            assert checker.check("networks", "update") is True

    def test_different_actions_independent(self):
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(
            os.environ,
            {
                "UNIFI_POLICY_DELETE": "false",
            },
            clear=True,
        ):
            assert checker.check("networks", "update") is True
            assert checker.check("networks", "delete") is False

    def test_category_map_resolves_shorthand(self):
        checker = PolicyGateChecker(
            server_prefix="network",
            category_map={"firewall": "firewall_policies"},
        )
        with patch.dict(
            os.environ,
            {
                "UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE": "false",
            },
            clear=True,
        ):
            assert checker.check("firewall", "update") is False

    def test_denial_message_includes_enable_hint(self):
        checker = PolicyGateChecker(server_prefix="network")
        msg = checker.denial_message("networks", "update")
        assert "UNIFI_POLICY_NETWORK_NETWORKS_UPDATE=true" in msg

    def test_protect_server_prefix(self):
        checker = PolicyGateChecker(server_prefix="protect")
        with patch.dict(
            os.environ,
            {
                "UNIFI_POLICY_PROTECT_UPDATE": "false",
            },
            clear=True,
        ):
            assert checker.check("camera", "update") is False

    def test_read_action_always_allowed(self):
        """Read actions bypass policy gates entirely."""
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(os.environ, {"UNIFI_POLICY_READ": "false"}, clear=True):
            assert checker.check("networks", "read") is True

    def test_boolean_parsing_variants(self):
        checker = PolicyGateChecker(server_prefix="network")
        for truthy in ("true", "True", "TRUE", "1", "yes", "on"):
            with patch.dict(os.environ, {"UNIFI_POLICY_UPDATE": truthy}, clear=True):
                assert checker.check("networks", "update") is True
        for falsy in ("false", "False", "FALSE", "0", "no", "off"):
            with patch.dict(os.environ, {"UNIFI_POLICY_UPDATE": falsy}, clear=True):
                assert checker.check("networks", "update") is False

    def test_create_action(self):
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(os.environ, {"UNIFI_POLICY_CREATE": "false"}, clear=True):
            assert checker.check("networks", "create") is False

    def test_delete_action(self):
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(os.environ, {"UNIFI_POLICY_DELETE": "false"}, clear=True):
            assert checker.check("networks", "delete") is False

    def test_old_format_env_var_compat(self):
        """Old UNIFI_PERMISSIONS_ vars are honored as fallback."""
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(os.environ, {"UNIFI_PERMISSIONS_NETWORKS_UPDATE": "false"}, clear=True):
            assert checker.check("networks", "update") is False

    def test_new_format_overrides_old(self):
        """New UNIFI_POLICY_ vars take priority over old format."""
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(
            os.environ,
            {
                "UNIFI_PERMISSIONS_NETWORKS_UPDATE": "false",
                "UNIFI_POLICY_NETWORK_NETWORKS_UPDATE": "true",
            },
            clear=True,
        ):
            assert checker.check("networks", "update") is True

    def test_old_format_allows(self):
        """Old UNIFI_PERMISSIONS_ vars can allow actions too."""
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(os.environ, {"UNIFI_PERMISSIONS_NETWORKS_CREATE": "true"}, clear=True):
            assert checker.check("networks", "create") is True

    def test_old_format_server_level_overrides_old(self):
        """Server-level new format takes priority over old format."""
        checker = PolicyGateChecker(server_prefix="network")
        with patch.dict(
            os.environ,
            {
                "UNIFI_PERMISSIONS_NETWORKS_UPDATE": "false",
                "UNIFI_POLICY_NETWORK_UPDATE": "true",
            },
            clear=True,
        ):
            assert checker.check("networks", "update") is True


class TestResolvePermissionMode:
    """Tests for permission mode resolution."""

    def test_default_is_confirm(self):
        with patch.dict(os.environ, {}, clear=True):
            assert resolve_permission_mode("network") == "confirm"

    def test_global_override(self):
        with patch.dict(os.environ, {"UNIFI_TOOL_PERMISSION_MODE": "bypass"}, clear=True):
            assert resolve_permission_mode("network") == "bypass"

    def test_server_overrides_global(self):
        with patch.dict(
            os.environ,
            {
                "UNIFI_TOOL_PERMISSION_MODE": "confirm",
                "UNIFI_NETWORK_TOOL_PERMISSION_MODE": "bypass",
            },
            clear=True,
        ):
            assert resolve_permission_mode("network") == "bypass"

    def test_invalid_mode_falls_back_to_confirm(self):
        with patch.dict(os.environ, {"UNIFI_TOOL_PERMISSION_MODE": "invalid"}, clear=True):
            assert resolve_permission_mode("network") == "confirm"

    def test_auto_confirm_compat(self):
        """UNIFI_AUTO_CONFIRM=true should map to bypass with deprecation."""
        with patch.dict(os.environ, {"UNIFI_AUTO_CONFIRM": "true"}, clear=True):
            assert resolve_permission_mode("network") == "bypass"

    def test_explicit_mode_overrides_auto_confirm(self):
        with patch.dict(
            os.environ,
            {
                "UNIFI_AUTO_CONFIRM": "true",
                "UNIFI_TOOL_PERMISSION_MODE": "confirm",
            },
            clear=True,
        ):
            assert resolve_permission_mode("network") == "confirm"

    def test_protect_server_mode(self):
        with patch.dict(
            os.environ,
            {
                "UNIFI_TOOL_PERMISSION_MODE": "confirm",
                "UNIFI_PROTECT_TOOL_PERMISSION_MODE": "bypass",
            },
            clear=True,
        ):
            assert resolve_permission_mode("protect") == "bypass"
            assert resolve_permission_mode("network") == "confirm"
