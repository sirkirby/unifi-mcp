"""The app bootstrap must snapshot the environment before any .env is loaded (real import order)."""

from unifi_mcp_shared.testing import assert_dotenv_file_indirection_refused


def test_dotenv_supplied_file_indirection_is_refused_and_never_read(tmp_path):
    assert_dotenv_file_indirection_refused(tmp_path, module="unifi_protect_mcp", env_prefix="PROTECT")
