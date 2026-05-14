"""CLI smoke test for `unifi-api graphql scaffold-resource`."""

from pathlib import Path

from typer.testing import CliRunner
from unifi_api.cli import app


def test_scaffold_resource_creates_type_file(tmp_path: Path, monkeypatch) -> None:
    """Scaffold writes a starter Strawberry type file and prints the path."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["graphql", "scaffold-resource", "network", "client", "--out-root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    target_file = tmp_path / "apps" / "api" / "src" / "unifi_api" / "graphql" / "types" / "network" / "client.py"
    assert target_file.exists(), result.output
    body = target_file.read_text(encoding="utf-8")
    assert "@strawberry.type" in body
    assert "class Client" in body
    assert "from_manager_output" in body
    assert "to_dict" in body
