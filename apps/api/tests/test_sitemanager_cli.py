"""CLI input channels and database changes share management contracts."""

import json
import shutil
import sqlite3
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner
from unifi_api.cli import app
from unifi_core.sitemanager.managers.inventory_manager import InventoryManager

from tests.test_sitemanager_connections import KEY


@pytest.fixture
def cli_config(tmp_path, migrated_state_dir, monkeypatch):
    template, _ = migrated_state_dir
    db = tmp_path / "state.db"
    shutil.copyfile(template / "state.db", db)
    config = tmp_path / "config.yaml"
    config.write_text(f"db:\n  path: {db}\n")
    monkeypatch.setenv("UNIFI_API_DB_KEY", "test-passphrase")
    return config, db


def call(config, verb, *args, input=None):
    return CliRunner().invoke(app, ["sitemanager", verb, "--config-path", str(config), *args], input=input)


@pytest.mark.parametrize("stdin", [False, True])
def test_cli_never_echoes_cloud_key(cli_config, monkeypatch, caplog, stdin):
    config, db = cli_config
    upstream = AsyncMock(side_effect=AssertionError("implicit upstream request"))
    monkeypatch.setattr(InventoryManager, "list_hosts", upstream)
    flags = ["--key-stdin"] if stdin else []
    created = call(config, "add", "--name", "Account", *flags, input=KEY + "\n")
    assert created.exit_code == 0, created.output
    assert KEY not in created.output
    assert json.loads(created.output.splitlines()[-1])["revision"] == 1
    listed = call(config, "list")
    assert listed.exit_code == 0
    assert json.loads(listed.output)["key_configured"] is True
    renamed = call(config, "update", "--name", "Renamed")
    assert renamed.exit_code == 0
    assert json.loads(renamed.output)["revision"] == 2
    rotated = call(config, "update", "--rotate-key", input="synthetic-rotated-cloud-key\n")
    assert rotated.exit_code == 0
    assert "synthetic-rotated-cloud-key" not in rotated.output
    assert json.loads(rotated.output.splitlines()[-1])["revision"] == 3
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM controllers").fetchone() == (0,)
        rows = conn.execute(
            "SELECT key_id_prefix,controller,detail FROM audit_log WHERE target LIKE 'sitemanager.%'"
        ).fetchall()
        assert rows == [("(cli)", None, None)] * 3
    deleted = call(config, "delete")
    assert deleted.exit_code == 0
    assert call(config, "list").output.strip() == "(no Site Manager connection)"
    assert KEY not in caplog.text
    upstream.assert_not_called()


def test_cli_probe_and_invalid_inputs_are_safe(cli_config, monkeypatch, caplog):
    config, _ = cli_config
    assert call(config, "add", "--name", "Account", "--key-stdin", input=KEY + "\n").exit_code == 0
    from unifi_api.services import sitemanager_managers

    closed = AsyncMock()

    class FakeConnection:
        def __init__(self, *, api_key):
            self.initialize = AsyncMock()
            self.close = closed

    monkeypatch.setattr(sitemanager_managers, "SiteManagerConnectionManager", FakeConnection)
    probe = AsyncMock(return_value=([{"cloud-secret": KEY}], None))
    monkeypatch.setattr(InventoryManager, "list_hosts", probe)
    result = call(config, "probe")
    assert result.exit_code == 0
    assert json.loads(result.output)["ok"] is True
    assert KEY not in result.output
    probe.assert_awaited_once_with(page_size=1)
    closed.assert_awaited_once()
    blank = call(config, "update", "--key-stdin", input="\n")
    assert blank.exit_code == 1
    assert "Check the Site Manager request fields" in blank.output
    assert KEY not in caplog.text


def test_cli_has_no_key_value_option():
    runner = CliRunner()
    help_result = runner.invoke(app, ["sitemanager", "--help"])
    assert help_result.exit_code == 0
    for command in ("add", "update", "list", "delete", "probe"):
        assert command in help_result.output
    for command in ("add", "update"):
        result = runner.invoke(app, ["sitemanager", command, "--help"])
        assert result.exit_code == 0
        assert "--key-stdin" in result.output
        assert "--api-key" not in result.output and "--site-manager-api-key" not in result.output
