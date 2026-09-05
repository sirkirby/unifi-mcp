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


def assert_dotenv_file_indirection_refused(tmp_path: Any, *, module: str, env_prefix: str) -> None:
    """A ``.env`` in the working directory must not be able to point the server at a file via ``_FILE``.

    Probes the real import order in a subprocess: the app bootstrap must snapshot
    the process environment before loading any ``.env``, so a ``.env``-supplied
    ``UNIFI_<PREFIX>_PASSWORD_FILE`` is refused (exit 6) and never read.
    """
    import os
    import subprocess
    import sys

    secret = tmp_path / "not-yours"
    secret.write_text("SENTINEL-dotenv-file-secret\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        f"UNIFI_{env_prefix}_PASSWORD_FILE={secret}\nUNIFI_{env_prefix}_HOST=10.9.9.9\nUNIFI_{env_prefix}_USERNAME=x\n",
        encoding="utf-8",
    )
    probe = tmp_path / "probe.py"
    probe.write_text(f"import {module}.bootstrap as b\nb.load_config()\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_")}
    result = subprocess.run(
        [sys.executable, str(probe)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 6, result.stderr
    assert "SENTINEL-dotenv-file-secret" not in result.stderr + result.stdout
