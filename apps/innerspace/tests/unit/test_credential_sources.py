"""Where the bundled config takes the InnerSpace host and login from, level by level."""

import os
import shlex
import sys
import uuid

import pytest

from unifi_innerspace_mcp import bootstrap
from unifi_mcp_shared import bootstrap as shared_bootstrap


@pytest.fixture
def env(monkeypatch):
    """A clean UNIFI_* environment over the real bundled config; returns a setter."""
    for name in [n for n in os.environ if n.startswith("UNIFI_") or n == "CONFIG_PATH"]:
        monkeypatch.delenv(name, raising=False)
    # Every variable here is set by the test, as the launcher would set it.
    monkeypatch.setattr(shared_bootstrap, "_TRUSTED_VARS", None)

    def set_env(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)

    return set_env


def _login() -> tuple[str, str, str]:
    cfg = bootstrap.load_config().unifi
    return cfg.host, cfg.username, cfg.password


SHARED = {"UNIFI_HOST": "gateway.invalid", "UNIFI_USERNAME": "shared-admin", "UNIFI_PASSWORD": "shared-pw"}


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        # No InnerSpace host: the shared level supplies host and login.
        ({}, ("gateway.invalid", "shared-admin", "shared-pw")),
        # The same host as the shared level: the shared login still applies.
        ({"UNIFI_INNERSPACE_HOST": "gateway.invalid"}, ("gateway.invalid", "shared-admin", "shared-pw")),
        # An InnerSpace login wins over the shared one.
        (
            {"UNIFI_INNERSPACE_USERNAME": "is-admin", "UNIFI_INNERSPACE_PASSWORD": "is-pw"},
            ("gateway.invalid", "is-admin", "is-pw"),
        ),
        # Empty InnerSpace variables count as unset.
        (
            {"UNIFI_INNERSPACE_HOST": "", "UNIFI_INNERSPACE_USERNAME": "", "UNIFI_INNERSPACE_PASSWORD": ""},
            ("gateway.invalid", "shared-admin", "shared-pw"),
        ),
    ],
)
def test_login_levels(env, product, expected):
    env(**SHARED, **product)

    assert _login() == expected


def test_innerspace_password_file_wins_over_the_shared_password(env, tmp_path):
    marker = f"file-{uuid.uuid4().hex[:8]}"
    secret = tmp_path / "password"
    secret.write_text(marker + "\n")
    secret.chmod(0o600)
    env(**SHARED, UNIFI_INNERSPACE_PASSWORD_FILE=str(secret))

    assert _login() == ("gateway.invalid", "shared-admin", marker)


def test_innerspace_password_command_wins_over_the_shared_password(env):
    marker = f"cmd-{uuid.uuid4().hex[:8]}"
    env(**SHARED, UNIFI_INNERSPACE_PASSWORD_COMMAND=shlex.join([sys.executable, "-c", f"print({marker!r})"]))

    assert _login() == ("gateway.invalid", "shared-admin", marker)


@pytest.mark.asyncio
async def test_a_tool_error_names_the_ignored_shared_password(env, monkeypatch):
    """Shared login, another InnerSpace host: no login is sent, and the tool's error says what to set."""
    from unifi_core.innerspace.managers.connection_manager import INTEGRATION_PREFIX
    from unifi_innerspace_mcp import runtime

    env(**SHARED, UNIFI_INNERSPACE_HOST="other.invalid")
    monkeypatch.setattr(runtime, "get_config", runtime.get_config.__wrapped__)
    manager = runtime.get_connection_manager.__wrapped__()
    operation = "list InnerSpace floor plans"
    try:
        assert await manager.initialize() is False
        with pytest.raises(Exception) as raised:
            await manager.request("GET", f"{INTEGRATION_PREFIX}/floor_plans", operation=operation)
    finally:
        await manager.close()
    # What a read tool returns for that error.
    result = runtime.tool_failure(operation, raised.value)

    # Non-empty only when load_server_config ran with the INNERSPACE prefix and cut the shared login.
    assert manager.auth_failure_hint
    assert "UNIFI_INNERSPACE_PASSWORD" in manager.auth_failure_hint
    assert result["success"] is False
    assert result["error"].count(manager.auth_failure_hint) == 1
    for value in (*SHARED.values(), "other.invalid"):
        assert value not in result["error"]
