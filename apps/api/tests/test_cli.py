"""CLI tests.

``--help`` runs through the real console script once; the subcommand help
screens run in-process through the Typer app.
"""

import subprocess

from typer.testing import CliRunner

from unifi_api.cli import app


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "--package", "unifi-api-server", "unifi-api-server", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_help_lists_subcommands() -> None:
    r = _run("--help")
    assert r.returncode == 0
    out = r.stdout + r.stderr
    assert "serve" in out
    assert "migrate" in out
    assert "keys" in out


def test_keys_help() -> None:
    r = CliRunner().invoke(app, ["keys", "--help"])
    assert r.exit_code == 0
    out = r.output
    assert "create" in out
    assert "list" in out
    assert "revoke" in out


def test_serve_help() -> None:
    r = CliRunner().invoke(app, ["serve", "--help"])
    assert r.exit_code == 0
