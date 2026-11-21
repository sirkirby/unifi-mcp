"""The app bootstrap must ignore project-selected secret files (real import order)."""

from unifi_mcp_shared.testing import (
    assert_dotenv_command_indirection_refused,
    assert_dotenv_file_indirection_refused,
)


def test_dotenv_supplied_file_indirection_is_refused_and_never_read(tmp_path):
    assert_dotenv_file_indirection_refused(tmp_path, module="unifi_innerspace_mcp", env_prefix="INNERSPACE")


def test_dotenv_cannot_make_the_server_run_a_credential_helper(tmp_path):
    assert_dotenv_command_indirection_refused(tmp_path, module="unifi_innerspace_mcp", env_prefix="INNERSPACE")
