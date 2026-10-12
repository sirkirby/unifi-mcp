"""With no controller host the server serves setup mode instead of exiting (real stdio)."""

import pytest

from unifi_mcp_shared.testing import assert_unconfigured_server_serves_setup_mode


@pytest.mark.parametrize("settings_file", [False, True], ids=["nothing-configured", "settings-file-missing"])
def test_unconfigured_server_serves_setup_mode(tmp_path, settings_file):
    assert_unconfigured_server_serves_setup_mode(
        tmp_path,
        module="unifi_access_mcp",
        env_prefix="ACCESS",
        plugin_name="unifi-access",
        tool_prefix="access",
        settings_file=settings_file,
    )
