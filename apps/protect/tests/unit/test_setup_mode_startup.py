"""With no controller host the server serves setup mode instead of exiting (real stdio)."""

import pytest

from unifi_mcp_shared.testing import assert_unconfigured_server_serves_setup_mode


@pytest.mark.parametrize("settings_file", [False, True], ids=["nothing-configured", "settings-file-missing"])
def test_unconfigured_server_serves_setup_mode(tmp_path, settings_file):
    assert_unconfigured_server_serves_setup_mode(
        tmp_path,
        module="unifi_protect_mcp",
        env_prefix="PROTECT",
        plugin_name="unifi-protect",
        tool_prefix="protect",
        settings_file=settings_file,
    )
