"""Codex setup starts the plugin's server once, as Codex launches it, so the first session finds it warm."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the fake uvx is a POSIX script")

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
PRODUCTS = ("network", "protect", "access")
MARKER = "FAKE-SERVER-OUTPUT-MARKER"

# A stand-in for uvx: records how it was started, then behaves as the mode file in its cwd says.
FAKE_UVX = f"""
import json, os, sys, time
from pathlib import Path
mode = Path("mode").read_text()
record = {{"argv": sys.argv[1:], "cwd": os.getcwd(), "env": sorted(os.environ), "pid": os.getpid(), "methods": []}}
def save():
    Path("record.json").write_text(json.dumps(record))
save()
if mode == "exit":
    sys.exit(3)
sys.stderr.write("{MARKER}\\n"); sys.stderr.flush()
request = json.loads(sys.stdin.readline())
record["methods"].append(request["method"]); save()
if mode == "silent":
    time.sleep(600)
sys.stdout.write("{MARKER} log line\\n")
reply = {{"jsonrpc": "2.0", "id": request["id"], "result": {{"serverInfo": {{"name": "fake"}}}}}}
sys.stdout.write(json.dumps(reply) + "\\n")
sys.stdout.flush()
for line in sys.stdin:
    record["methods"].append(json.loads(line)["method"]); save()
record["stdin_closed"] = True
save()
"""


def load_setup_config(product: str):
    path = PLUGINS / f"unifi-{product}" / "scripts" / "setup_config.py"
    spec = importlib.util.spec_from_file_location(f"setup_config_warm_{product}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_bin(tmp_path: Path, *names: str) -> Path:
    directory = tmp_path / "bin"
    directory.mkdir(exist_ok=True)
    for name in names:
        path = directory / name
        path.write_text("#!" + sys.executable + "\n" + (FAKE_UVX if name == "uvx" else ""), encoding="utf-8")
        path.chmod(0o755)
    return directory


def plugin_copy(tmp_path: Path, product: str, mode: str) -> Path:
    root = tmp_path / "plugin" / f"unifi-{product}"
    shutil.copytree(PLUGINS / f"unifi-{product}", root)
    (root / "mode").write_text(mode, encoding="utf-8")
    return root


def launch_args(product: str) -> list[str]:
    entry = json.loads((PLUGINS / f"unifi-{product}" / ".mcp.codex.json").read_text(encoding="utf-8"))
    entry = entry["mcpServers"][f"unifi-{product}"]
    assert entry["command"] == "uvx"
    return entry["args"]


def record(root: Path) -> dict:
    return json.loads((root / "record.json").read_text(encoding="utf-8"))


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize("product", PRODUCTS)
def test_warm_up_runs_the_codex_launch_command_without_settings(tmp_path, monkeypatch, capsys, product) -> None:
    module = load_setup_config(product)
    root = plugin_copy(tmp_path, product, "answer")
    monkeypatch.setenv("PATH", str(fake_bin(tmp_path, "uvx")))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # None of these reach the server: Codex passes only its core variables and the plugin's own.
    monkeypatch.setenv("UNIFI_SETTINGS_FILE", str(tmp_path / "settings.env"))
    monkeypatch.setenv(f"UNIFI_{product.upper()}_HOST", "192.0.2.1")
    monkeypatch.setenv("UNIFI_PASSWORD_COMMAND", "fake-provider")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "other-cache"))

    note = module.warm_up(root, f"unifi-{product}")

    seen = record(root)
    assert seen["argv"] == launch_args(product)
    assert Path(seen["cwd"]).resolve() == root.resolve()
    assert "HOME" in seen["env"]
    assert not [key for key in seen["env"] if key.startswith(("UNIFI_", "UV_"))]
    assert set(seen["env"]) - set(module.CODEX_SERVER_ENV) <= {"__CF_USER_TEXT_ENCODING", "PWD", "SHLVL", "_"}
    # Stopped as a client does once initialize is answered: no further request, then stdin closed.
    assert seen["methods"] == ["initialize"]
    assert seen.get("stdin_closed") is True
    assert not pid_alive(seen["pid"])
    assert note.startswith("Started unifi-" + product + "-mcp==")
    assert MARKER not in note + capsys.readouterr().out


@pytest.mark.parametrize("mode", ["silent", "exit"])
def test_warm_up_fails_softly(tmp_path, monkeypatch, mode) -> None:
    module = load_setup_config("network")
    root = plugin_copy(tmp_path, "network", mode)
    monkeypatch.setenv("PATH", str(fake_bin(tmp_path, "uvx")))

    started = time.monotonic()
    note = module.warm_up(root, "unifi-network", timeout=1)

    assert time.monotonic() - started < 15
    assert note.startswith("Notice: unifi-network-mcp==")
    assert "may start without the unifi-network tools" in note
    assert MARKER not in note
    assert not pid_alive(record(root)["pid"])


def test_warm_up_without_uvx_fails_softly(tmp_path, monkeypatch) -> None:
    module = load_setup_config("network")
    root = plugin_copy(tmp_path, "network", "answer")
    monkeypatch.setenv("PATH", str(fake_bin(tmp_path)))

    assert module.warm_up(root, "unifi-network").startswith("Notice: ")
    assert not (root / "record.json").exists()


def run_setup(tmp_path: Path, root: Path, *args: str, stdin: bytes = b"") -> subprocess.CompletedProcess:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith(("UNIFI_", "CODEX_", "OPENCLAW_"))
    }
    environment.update(
        HOME=str(tmp_path / "home"),
        CODEX_HOME=str(tmp_path / "codex"),
        OPENCLAW_STATE_DIR=str(tmp_path / "openclaw"),
        PATH=str(fake_bin(tmp_path, "uvx", "codex", "openclaw")),
    )
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "setup_config.py"), *args],
        input=stdin,
        env=environment,
        capture_output=True,
        check=False,
    )


SETTINGS = b"UNIFI_NETWORK_HOST=192.0.2.1\0UNIFI_NETWORK_USERNAME=fake-user\0"


@pytest.mark.parametrize("mode", ["answer", "exit"])
def test_codex_setup_saves_then_warms_and_a_failed_warm_up_changes_nothing(tmp_path, mode) -> None:
    root = plugin_copy(tmp_path, "network", mode)
    (tmp_path / "codex").mkdir()
    config = tmp_path / "codex" / "config.toml"
    config.write_text('model = "fixture"\n', encoding="utf-8")

    completed = run_setup(tmp_path, root, "--target", "codex", "--pairs", stdin=SETTINGS)

    assert completed.returncode == 0
    lines = completed.stdout.decode().splitlines()
    assert lines[0].startswith("Saved the Codex settings for unifi-network")
    assert lines[-2] == "Restart Codex to load the settings. Values are omitted."
    assert lines[-1].startswith("Started " if mode == "answer" else "Notice: unifi-network-mcp==")
    assert MARKER.encode() not in completed.stdout + completed.stderr
    settings = (tmp_path / "home" / ".config" / "unifi-mcp" / "network.env").read_text(encoding="utf-8")
    assert 'UNIFI_NETWORK_HOST="192.0.2.1"' in settings
    assert config.read_text(encoding="utf-8") == 'model = "fixture"\n'
    assert record(root)["argv"] == launch_args("network")


def test_codex_refresh_warms_the_server(tmp_path) -> None:
    root = plugin_copy(tmp_path, "network", "answer")
    (tmp_path / "codex").mkdir()
    assert run_setup(tmp_path, root, "--target", "codex", "--pairs", stdin=SETTINGS).returncode == 0
    (root / "record.json").unlink()

    completed = run_setup(tmp_path, root, "--target", "codex", "--refresh")

    assert completed.returncode == 0
    lines = completed.stdout.decode().splitlines()
    assert lines[0].startswith("Nothing to convert")
    assert lines[-1].startswith("Started unifi-network-mcp==")
    assert record(root)["methods"] == ["initialize"]


@pytest.mark.parametrize(
    "args",
    [
        ("--target", "codex", "--pairs", "--dry-run"),
        ("--target", "codex", "--check"),
        ("--target", "openclaw", "--pairs"),
    ],
)
def test_only_saving_codex_setup_starts_the_server(tmp_path, args) -> None:
    root = plugin_copy(tmp_path, "network", "answer")

    completed = run_setup(tmp_path, root, *args, stdin=SETTINGS)

    assert completed.returncode == 0
    assert not (root / "record.json").exists()
