"""Regression tests for bootstrap dotenv discovery."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("dotenv_value", "environment_value", "expected"),
    [
        ("from-dotenv", None, "from-dotenv"),
        ("from-dotenv", "from-environment", "from-environment"),
        (None, None, "MISSING"),
    ],
)
def test_bootstrap_loads_cwd_dotenv_without_overriding_environment(
    tmp_path,
    dotenv_value,
    environment_value,
    expected,
):
    marker = "UNIFI_TEST_PROTECT_CWD_DOTENV"
    if dotenv_value is not None:
        (tmp_path / ".env").write_text(f"{marker}={dotenv_value}\n", encoding="utf-8")

    probe = tmp_path / "probe.py"
    probe.write_text(
        f'import os\nimport unifi_protect_mcp.bootstrap\nprint(os.getenv("{marker}", "MISSING"))\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop(marker, None)
    if environment_value is not None:
        env[marker] = environment_value

    result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == expected
