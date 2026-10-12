"""Reusable assertion helpers for MCP server integration tests."""

from __future__ import annotations

import base64
from importlib.metadata import version
from typing import Any

from unifi_mcp_shared.metadata import PROJECT_WEBSITE_URL


def assert_server_initialization_metadata(server: Any, *, package_name: str) -> None:
    """Assert that ``server`` exposes the expected MCP initialization metadata.

    Each app's integration test invokes this with its own FastMCP server
    instance so the project-wide initialize-response contract is asserted in
    exactly one place.
    """
    options = server._lowlevel_server.create_initialization_options()
    assert options.server_name == package_name
    assert options.server_version == version(package_name)
    assert options.website_url == PROJECT_WEBSITE_URL
    assert options.icons is not None
    assert [icon.sizes for icon in options.icons] == [["48x48"], ["96x96"], ["192x192"]]
    assert {icon.mime_type for icon in options.icons} == {"image/png"}
    decoded = base64.b64decode(options.icons[0].src.removeprefix("data:image/png;base64,"))
    assert decoded.startswith(b"\x89PNG\r\n\x1a\n")


def _probe_dotenv_indirection(
    tmp_path: Any, *, module: str, dotenv: str, forbid_open: str | None = None, extra: str = ""
) -> Any:
    """Start the app bootstrap in a subprocess whose working directory holds *dotenv*.

    Runs the real import order rather than a monkeypatched approximation. The
    server never discovers a project ``.env``, so the names it sets must not
    reach the environment at all; when *forbid_open* is given, an audit hook
    fails the probe if that path is opened.
    """
    import os
    import subprocess
    import sys

    (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
    hook = ""
    if forbid_open is not None:
        hook = (
            f"forbidden = {forbid_open!r}\n"
            "def _forbid(event, args):\n"
            "    if event == 'open' and args[0] == forbidden:\n"
            "        raise AssertionError('Project-selected path was opened')\n"
            "sys.addaudithook(_forbid)\n"
        )
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os, sys\n" + hook + f"import {module}.bootstrap as b\ncfg = b.load_config()\n" + extra,
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_") and k != "CONFIG_PATH"}
    return subprocess.run(
        [sys.executable, str(probe)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60, check=False
    )


def assert_dotenv_file_indirection_refused(tmp_path: Any, *, module: str, env_prefix: str) -> None:
    """A ``.env`` in the working directory must not be able to point the server at a file via ``_FILE``.

    Project dotenv values never enter the environment, so the spelling is not
    honoured and the file is never opened. The historical helper name is
    retained for downstream tests.
    """
    secret = tmp_path / "not-yours"
    secret.write_text("SENTINEL-dotenv-file-secret\n", encoding="utf-8")
    result = _probe_dotenv_indirection(
        tmp_path,
        module=module,
        dotenv=(
            f"UNIFI_{env_prefix}_PASSWORD_FILE={secret}\n"
            f"UNIFI_{env_prefix}_HOST=10.9.9.9\nUNIFI_{env_prefix}_USERNAME=x\n"
        ),
        forbid_open=str(secret),
        extra=(
            f"assert 'UNIFI_{env_prefix}_PASSWORD_FILE' not in os.environ\n"
            "assert str(cfg.unifi.host) == ''\n"
            "assert str(cfg.unifi.password) == ''\n"
        ),
    )
    assert result.returncode == 0, result.stderr
    assert "SENTINEL-dotenv-file-secret" not in result.stderr + result.stdout


def assert_dotenv_command_indirection_refused(tmp_path: Any, *, module: str, env_prefix: str) -> None:
    """A ``.env`` in the working directory must not be able to make the server run a program.

    The stronger half of the same boundary: ``_FILE`` would leak a file the
    operator did not choose, but ``_COMMAND`` would execute code. The helper
    writes a marker before printing, so the assertion is that it never ran at
    all -- not merely that its output was discarded.
    """
    import os

    if os.name == "nt":  # pragma: no cover - the probe writes a /bin/sh helper
        import pytest

        pytest.skip("the command-provider probe needs a POSIX shell")
    marker = tmp_path / "helper-ran"
    helper = tmp_path / "helper.sh"
    helper.write_text(
        f'#!/bin/sh\ntouch "{marker}"\nprintf %s SENTINEL-dotenv-command-secret\n',
        encoding="utf-8",
    )
    helper.chmod(0o755)
    result = _probe_dotenv_indirection(
        tmp_path,
        module=module,
        dotenv=(
            f"UNIFI_{env_prefix}_PASSWORD_COMMAND={helper}\n"
            f"UNIFI_{env_prefix}_HOST=10.9.9.9\nUNIFI_{env_prefix}_USERNAME=x\n"
        ),
        extra=(
            f"assert 'UNIFI_{env_prefix}_PASSWORD_COMMAND' not in os.environ\nassert str(cfg.unifi.password) == ''\n"
        ),
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists(), "a .env-supplied _COMMAND was executed"
    assert "SENTINEL-dotenv-command-secret" not in result.stderr + result.stdout


_SETTINGS_PROBE = """\
import asyncio, socket, sys
from unittest import mock

def _no_network(event, args):
    if event == "socket.connect" and args[0].family in (socket.AF_INET, socket.AF_INET6):
        raise AssertionError("the startup probe must not open a network connection")
sys.addaudithook(_no_network)

import {module}.main as m

assert str(m.config.unifi.host) == "192.0.2.11", "host"
assert int(m.config.unifi.port) == 9, "port"
assert str(m.config.unifi.password) == "{password}", "password provider"
assert m.UNIFI_TOOL_REGISTRATION_MODE == "meta_only", "registration mode"

calls = []

async def _record(name, result=None):
    calls.append(name)
    return result

m.connection_manager.initialize = lambda *a, **k: _record("initialize", False)
m.event_manager.start_listening = lambda *a, **k: _record("start_listening")
transport = mock.AsyncMock()
with mock.patch("unifi_mcp_shared.transport.run_transports", transport):
    asyncio.run(m.main_async())
assert transport.await_count == 1, "transport"
assert "initialize" in calls, calls

@m.server.tool(name="settings_file_probe", permission_category="settings_probe", permission_action="delete")
async def probe(confirm: bool = False):
    return {{"success": True}}

denied = asyncio.run(probe())
assert denied["success"] is False and "disabled by policy" in denied["error"], "policy gate"
print("settings-file-probe-ok")
"""


def assert_settings_file_configures_server(tmp_path: Any, *, module: str, env_prefix: str) -> None:
    """Start the app with only ``UNIFI_SETTINGS_FILE`` and assert it sees the file.

    Runs the real import order in a subprocess whose environment holds no other
    ``UNIFI_*`` variable. Controller I/O and the MCP transport are replaced, and
    an audit hook fails the probe on any network connection.
    """
    import os
    import subprocess
    import sys

    password = "SENTINEL-settings-file-password"
    secret = tmp_path / "password"
    secret.write_text(password + "\n", encoding="utf-8")
    secret.chmod(0o600)
    settings = tmp_path / "settings.env"
    settings.write_text(
        f"UNIFI_{env_prefix}_HOST=192.0.2.11\n"
        f"UNIFI_{env_prefix}_PORT=9\n"
        f"UNIFI_{env_prefix}_USERNAME=fake-user\n"
        f"UNIFI_{env_prefix}_PASSWORD_FILE={secret}\n"
        f"UNIFI_POLICY_{env_prefix}_DELETE=false\n"
        "UNIFI_TOOL_REGISTRATION_MODE=meta_only\n",
        encoding="utf-8",
    )
    settings.chmod(0o600)
    probe = tmp_path / "probe.py"
    probe.write_text(_SETTINGS_PROBE.format(module=module, password=password), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_") and k != "CONFIG_PATH"}
    env["UNIFI_SETTINGS_FILE"] = str(settings)
    result = subprocess.run(
        [sys.executable, str(probe)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "settings-file-probe-ok" in result.stdout
    assert password not in result.stderr
