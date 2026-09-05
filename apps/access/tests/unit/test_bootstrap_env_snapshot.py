"""A .env in the working directory must not be able to run a program via _COMMAND.

The app bootstrap snapshots the process environment before loading any .env, and
resolve_env honours UNIFI_*_FILE / _COMMAND only for variables in that snapshot.
This probes the real import order in a subprocess, the same way
test_bootstrap_dotenv.py does.
"""

import os
import subprocess
import sys


def test_dotenv_supplied_command_is_refused_and_never_runs(tmp_path):
    marker = tmp_path / "PWNED"
    (tmp_path / ".env").write_text(
        f"UNIFI_ACCESS_PASSWORD_COMMAND=touch {marker}\nUNIFI_ACCESS_HOST=10.9.9.9\nUNIFI_ACCESS_USERNAME=x\n",
        encoding="utf-8",
    )
    probe = tmp_path / "probe.py"
    probe.write_text("import unifi_access_mcp.bootstrap as b\nb.load_config()\n", encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_")}
    result = subprocess.run(
        [sys.executable, str(probe)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60, check=False
    )

    assert result.returncode == 6, result.stderr
    assert "UNIFI_ACCESS_PASSWORD_COMMAND" in result.stderr
    assert ".env" in result.stderr
    assert not marker.exists()
