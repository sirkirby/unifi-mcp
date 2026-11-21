"""A server configured only by UNIFI_SETTINGS_FILE sees its host and credentials (real import order).

Runs the real import order in a subprocess whose environment holds no other
``UNIFI_*`` variable. The console connection and the MCP transport are replaced,
and an audit hook fails the probe on any network connection.
"""

import os
import subprocess
import sys

_PROBE = """\
import asyncio, socket, sys
from unittest import mock

def _no_network(event, args):
    if event == "socket.connect" and args[0].family in (socket.AF_INET, socket.AF_INET6):
        raise AssertionError("the startup probe must not open a network connection")
sys.addaudithook(_no_network)

import unifi_innerspace_mcp.main as m

assert str(m.config.unifi.host) == "192.0.2.11", "host"
assert int(m.config.unifi.port) == 9, "port"
assert str(m.config.unifi.password) == "{password}", "password provider"
assert m.UNIFI_TOOL_REGISTRATION_MODE == "meta_only", "registration mode"

calls = []

async def _initialize(*args, **kwargs):
    calls.append("initialize")
    return False

m.connection_manager.initialize = _initialize

async def _serve(**kwargs):
    # The console connects in the background; serve until that is done.
    for task in asyncio.all_tasks():
        if task.get_name() == "innerspace-startup-connect":
            await task

transport = mock.AsyncMock(side_effect=_serve)
with mock.patch("unifi_mcp_shared.transport.run_transports", transport):
    asyncio.run(m.main_async())
assert transport.await_count == 1, "transport"
assert calls == ["initialize"], calls
print("settings-file-probe-ok")
"""


def test_settings_file_alone_configures_the_server(tmp_path):
    secret_value = "SENTINEL-settings-file-secret"
    secret = tmp_path / "secret-file"
    secret.write_text(secret_value + "\n", encoding="utf-8")
    secret.chmod(0o600)
    settings = tmp_path / "settings.env"
    settings.write_text(
        "UNIFI_INNERSPACE_HOST=192.0.2.11\n"
        "UNIFI_INNERSPACE_PORT=9\n"
        "UNIFI_INNERSPACE_USERNAME=fake-user\n"
        f"UNIFI_INNERSPACE_PASSWORD_FILE={secret}\n"
        "UNIFI_TOOL_REGISTRATION_MODE=meta_only\n",
        encoding="utf-8",
    )
    settings.chmod(0o600)
    probe = tmp_path / "probe.py"
    probe.write_text(_PROBE.format(password=secret_value), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_") and k != "CONFIG_PATH"}
    env["UNIFI_SETTINGS_FILE"] = str(settings)

    result = subprocess.run(
        [sys.executable, str(probe)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120, check=False
    )

    assert result.returncode == 0, result.stderr
    assert "settings-file-probe-ok" in result.stdout
    assert secret_value not in result.stderr
