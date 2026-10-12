"""A server configured only by UNIFI_SETTINGS_FILE sees its host and gates (real import order)."""

from unifi_mcp_shared.testing import assert_settings_file_configures_server


def test_settings_file_alone_configures_the_server(tmp_path):
    assert_settings_file_configures_server(tmp_path, module="unifi_protect_mcp", env_prefix="PROTECT")
