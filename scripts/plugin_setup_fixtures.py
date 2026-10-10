#!/usr/bin/env python3
"""Credential-free integration fixtures for the shell and PowerShell harnesses."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path


def toml_literal(value):
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + "=" + toml_literal(v) for k, v in value.items()) + "}"
    return json.dumps(value, ensure_ascii=False)


def write_toml(path, document):
    lines = [json.dumps(k) + "=" + toml_literal(v) for k, v in document.items() if k != "mcp_servers"]
    for name, entry in document.get("mcp_servers", {}).items():
        lines.append("[mcp_servers." + json.dumps(name) + "]")
        lines.extend(json.dumps(k) + "=" + toml_literal(v) for k, v in entry.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fake_client(name):
    args = sys.argv[3:]
    with open(os.environ["FIXTURE_ARGV"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps([name] + args, ensure_ascii=False) + "\n")
    failure = os.environ.get("FIXTURE_FAIL")
    if (failure == "register" and args[:2] in (["mcp", "add"], ["mcp", "set"])) or (
        failure == "validate" and args[:2] in (["mcp", "get"], ["config", "validate"])
    ):
        # Simulate an ill-behaved CLI: its diagnostics must never reach the user.
        print(os.environ["FIXTURE_SECRET"])
        print(os.environ["FIXTURE_SECRET"], file=sys.stderr)
        sys.exit(2)
    if name == "uvx":
        return
    if name == "codex":
        path = Path(os.environ["CODEX_HOME"]) / "config.toml"
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        registry = document.setdefault("mcp_servers", {})
        if args[:2] == ["mcp", "add"]:
            registry[args[2]] = {"command": "uvx", "args": args[args.index("--") + 2 :]}
        elif args[:2] == ["mcp", "remove"]:
            registry.pop(args[2], None)
        elif args[:2] == ["mcp", "get"]:
            print(json.dumps({"transport": registry[args[2]]}))
            return
        write_toml(path, document)
    elif name == "openclaw":
        path = Path(os.environ["OPENCLAW_CONFIG_PATH"])
        document = json.loads(path.read_text(encoding="utf-8"))
        if args[:2] == ["mcp", "set"]:
            document.setdefault("mcp", {}).setdefault("servers", {})[args[2]] = json.loads(args[3])
            path.write_text(json.dumps(document), encoding="utf-8")
        elif args[:2] == ["config", "validate"]:
            assert isinstance(document["mcp"]["servers"], dict)


def executable(directory, name, source):
    if os.name == "nt":
        # Native Windows client CLIs commonly resolve through .cmd launchers.
        path = directory / (name + ".cmd")
        path.write_text(
            '@echo off\n"'
            + sys.executable
            + '" "'
            + str(Path(__file__).resolve())
            + '" --fake-client '
            + name
            + " %*\n",
            encoding="utf-8",
        )
    else:
        path = directory / name
        path.write_text("#!" + sys.executable + "\n" + source, encoding="utf-8")
        path.chmod(0o755)


class Fixtures:
    def __init__(self, root, shell, powershell):
        self.root = root
        self.shell = shell
        self.powershell = powershell
        self.passes = 0
        self.repo = Path(__file__).resolve().parents[1]

    def check(self, condition, label):
        if not condition:
            raise AssertionError(label)
        self.passes += 1

    def check_script_parity(self):
        """Keep shipped setup implementations byte-identical across products."""
        reference = self.repo / "plugins/unifi-network/scripts"
        for product in ("network", "protect", "access"):
            scripts = self.repo / f"plugins/unifi-{product}/scripts"
            for filename in (
                "set-env.sh",
                "set-env.ps1",
                "check-prereqs.sh",
                "check-prereqs.ps1",
                "setup_config.py",
            ):
                self.check(
                    (scripts / filename).read_bytes() == (reference / filename).read_bytes(),
                    "cross-product script parity",
                )

    def run(self):
        self.check_script_parity()
        for product in ("network", "protect", "access"):
            for target in ("claude", "codex", "openclaw"):
                self.scenario(product, target)

    def scenario(self, product, target):
        workspace = self.root / (product + "-" + target)
        workspace.mkdir()
        bindir = workspace / "bin"
        bindir.mkdir()
        for name in ("uvx", "codex", "openclaw"):
            executable(
                bindir,
                name,
                "import runpy,sys\nsys.argv=["
                + repr(str(Path(__file__).resolve()))
                + ", '--fake-client', "
                + repr(name)
                + "]+sys.argv[1:]\nrunpy.run_path(sys.argv[0],run_name='__main__')\n",
            )
        executable(bindir, "fixture-provider", "pass\n")
        environment = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_")}
        environment.update(
            HOME=str(workspace),
            USERPROFILE=str(workspace),
            CODEX_HOME=str(workspace / "codex"),
            CLAUDE_CONFIG_DIR=str(workspace / "claude"),
            OPENCLAW_STATE_DIR=str(workspace / "openclaw"),
            OPENCLAW_CONFIG_PATH=str(workspace / "openclaw/openclaw.json"),
            PATH=str(bindir) + os.pathsep + os.environ["PATH"],
            FIXTURE_ARGV=str(workspace / "argv.jsonl"),
        )
        secret = 'FAKE-only "quotes" $dollar \\ slash spaces Ω 😀'
        environment["FIXTURE_SECRET"] = secret
        base = f"UNIFI_{product.upper()}_PASSWORD"
        scripts = self.repo / f"plugins/unifi-{product}/scripts"
        if self.powershell:
            command = [
                self.powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(scripts / "set-env.ps1"),
                "-Target",
                target,
                "-InputJson",
            ]
        else:
            command = [self.shell, str(scripts / "set-env.sh"), "--target", target, "--input-json"]
        if target == "claude":
            path = workspace / ".claude/settings.local.json"
            fixture = {
                "permissions": {"allow": ['Bash(grep "x{2,}")']},
                "deep": {"nested": [1]},
                "env": {"KEEP": "old", base: "FAKE-old"},
            }
        else:
            path = workspace / ("codex/config.toml" if target == "codex" else "openclaw/openclaw.json")
            entry = {"command": "uvx", "args": ["previous"], "env": {"KEEP": "old", base: "FAKE-old"}}
            registry = {f"unifi-{product}": entry, "unrelated": {"command": "keep", "env": {"KEEP": "yes"}}}
            fixture = (
                {"model": "fixture", "mcp_servers": registry}
                if target == "codex"
                else {"custom": {"keep": [True]}, "mcp": {"servers": registry}}
            )
        path.parent.mkdir()

        def seed():
            if target == "codex":
                write_toml(path, fixture)
            else:
                path.write_text(json.dumps(fixture), encoding="utf-8")

        def load():
            return (
                tomllib.loads(path.read_text(encoding="utf-8"))
                if target == "codex"
                else json.loads(path.read_text(encoding="utf-8"))
            )

        def get_env(data):
            if target == "claude":
                return data["env"]
            registry = data["mcp_servers"] if target == "codex" else data["mcp"]["servers"]
            return registry[f"unifi-{product}"]["env"]

        def invoke(patch, expected=0, extra=None):
            env = dict(environment, **(extra or {}))
            result = subprocess.run(
                command,
                input=patch if isinstance(patch, bytes) else json.dumps(patch).encode(),
                cwd=workspace,
                env=env,
                capture_output=True,
                timeout=30,
            )
            self.check(result.returncode == expected if expected == 0 else result.returncode != 0, "setup exit status")
            self.check(secret.encode() not in result.stdout + result.stderr, "no secret in stdout/stderr")
            argv_path = workspace / "argv.jsonl"
            if argv_path.exists():
                self.check(secret not in argv_path.read_text(encoding="utf-8"), "no secret in client argv")
            return result

        seed()
        before = path.read_bytes()
        invoke(b"{ malformed JSON patch", 1)
        self.check(path.read_bytes() == before, "malformed stdin JSON preserves prior configuration")
        for malformed in (
            (b"{ broken FAKE-only", b"[]", b'{"env":[]}') if target == "claude" else (b"{ broken FAKE-only",)
        ):
            path.write_bytes(malformed)
            invoke({base: secret}, 1)
            self.check(path.read_bytes() == malformed, "invalid existing document preserved")
        seed()
        for patch in (
            {"bad-key": secret},
            {base + "_VAULT": secret},
            {base + "_FILE": "relative"},
            {base + "_COMMAND": "./relative"},
            {base + "_COMMAND": "nonexistent-fixture-provider-command"},
            {base + "_FILE": str(workspace / "missing-credential")},
            {base: secret, base + "_FILE": str(workspace / "credential")},
            {base: [secret]},
        ):
            invoke(patch, 1)
            self.check(path.read_bytes() == before, "invalid key/provider/type preserved prior configuration")
        # Missing uvx, then missing client: PATH contains no real executable.
        isolated = workspace / "isolated"
        isolated.mkdir()
        if os.name == "nt":
            # Keep the interpreter beside its Windows standard library.
            isolated_path = str(isolated) + os.pathsep + str(Path(sys.executable).parent)
        else:
            (isolated / "python3").symlink_to(sys.executable)
            for name in ("dirname",):
                candidate = shutil.which(name)
                if candidate:
                    (isolated / name).symlink_to(candidate)
            isolated_path = str(isolated)
        invoke({base: secret}, 1, {"PATH": isolated_path})
        self.check(path.read_bytes() == before, "missing dependency preserves configuration")
        if not self.powershell and os.name != "nt":
            (isolated / "python3").unlink()
            invoke({base: secret}, 1, {"PATH": isolated_path})
            self.check(path.read_bytes() == before, "missing Python preserves configuration")
            (isolated / "python3").symlink_to(sys.executable)
        if target != "claude":
            executable(isolated, "uvx", "pass\n")
            invoke({base: secret}, 1, {"PATH": isolated_path})
            self.check(path.read_bytes() == before, "missing client preserves registration")
            invoke({base: secret}, 1, {"FIXTURE_FAIL": "register"})
            self.check(path.read_bytes() == before, "failed client registration preserves exact registry bytes")
            invoke({base: secret}, 1, {"FIXTURE_FAIL": "validate"})
            self.check(path.read_bytes() == before, "failed client validation preserves exact registry bytes")
        invoke({base: secret})
        data = load()
        self.check(get_env(data)[base] == secret, "special characters round-trip")
        self.check(get_env(data)["KEEP"] == "old", "unrelated environment preserved")
        if target == "claude":
            self.check(
                data["permissions"] == fixture["permissions"] and data["deep"] == fixture["deep"],
                "unrelated nested settings preserved",
            )
        else:
            registry = data["mcp_servers"] if target == "codex" else data["mcp"]["servers"]
            original_registry = fixture["mcp_servers"] if target == "codex" else fixture["mcp"]["servers"]
            self.check(registry["unrelated"] == original_registry["unrelated"], "unrelated registration preserved")
        for small in ("x", "true", "1234"):
            result = invoke({base: small})
            self.check(small.encode() not in result.stdout + result.stderr, "short/boolean-like credentials omitted")
        # Provider switching clears only siblings at the chosen precedence tier.
        filename = str(workspace / "credential-Ω")
        Path(filename).write_text("FAKE-file-provider", encoding="utf-8")
        (workspace / "shared").write_text("FAKE-shared-provider", encoding="utf-8")
        invoke({base + "_FILE": filename, "UNIFI_PASSWORD_FILE": str(workspace / "shared")})
        env = get_env(load())
        self.check(
            base not in env and env[base + "_FILE"] == filename and "UNIFI_PASSWORD_FILE" in env,
            "plain-to-file switching and shared precedence",
        )
        invoke({base + "_COMMAND": "fixture-provider --no-prompt"})
        env = get_env(load())
        self.check(
            base + "_FILE" not in env and env[base + "_COMMAND"] == "fixture-provider --no-prompt",
            "file-to-command switching",
        )
        invoke({base + "_COMMAND": None})
        self.check(base + "_COMMAND" not in get_env(load()), "null provider deletion")
        if target == "codex":
            # Installed Codex plugins include a version directory in their path.
            cached = workspace / "cache" / f"unifi-{product}" / "9.8.7" / "scripts"
            cached.mkdir(parents=True)
            for source in scripts.iterdir():
                if source.is_file():
                    shutil.copy2(source, cached / source.name)
            suffix = "set-env.ps1" if self.powershell else "set-env.sh"
            command[command.index(str(scripts / suffix))] = str(cached / suffix)
            invoke({f"UNIFI_{product.upper()}_HOST": "192.0.2.99"})
            self.check(
                get_env(load())[f"UNIFI_{product.upper()}_HOST"] == "192.0.2.99",
                "versioned plugin cache uses semantic server name",
            )
        # Inject at the actual replace boundary through Python's test import hook.
        injection = workspace / "injection"
        injection.mkdir()
        (injection / "sitecustomize.py").write_text(
            "import os,time\nfrom pathlib import Path\n"
            "def replace(src,dst):\n"
            ' if os.environ.get("FIXTURE_REPLACE_FAIL"): raise OSError("FAKE-only write failure")\n'
            ' Path(os.environ["FIXTURE_READY"]).write_text(str(os.getpid()))\n'
            " while True: time.sleep(.02)\n"
            "os.replace=replace\n",
            encoding="utf-8",
        )
        marker = workspace / "ready"
        before = path.read_bytes()
        invoke(
            {base: secret},
            1,
            {"PYTHONPATH": str(injection), "FIXTURE_REPLACE_FAIL": "1", "FIXTURE_READY": str(marker)},
        )
        self.check(path.read_bytes() == before, "failed atomic replacement preserves prior configuration")
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace,
            env=dict(environment, PYTHONPATH=str(injection), FIXTURE_READY=str(marker)),
        )
        process.stdin.write(json.dumps({base: secret}).encode())
        process.stdin.close()
        process.stdin = None
        try:
            deadline = time.monotonic() + 20
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.check(marker.exists(), "interruption reached atomic replacement boundary")
            if self.powershell and os.name == "nt":
                # A forced Windows interruption stops the child process tree.
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
            elif self.powershell:
                # Stop the helper at the boundary, rather than its PowerShell parent.
                os.kill(int(marker.read_text()), signal.SIGTERM)
            else:
                process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=20)
            self.check(process.returncode != 0, "interrupted setup exits nonzero")
            self.check(path.read_bytes() == before, "interrupted write leaves exact prior config and registration")
            self.check(secret.encode() not in stdout + stderr, "interrupted output omits secret")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        print(f"  [OK] {product}/{target}: failures, escaping, provider switching, interruption, argv privacy")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shell", default="/bin/bash")
    parser.add_argument("--powershell")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix=".setup-fixtures-", dir=repo) as temporary:
        fixtures = Fixtures(Path(temporary), args.shell, args.powershell)
        fixtures.run()
        print(f"Fixture assertions: {fixtures.passes} passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fake-client":
        fake_client(sys.argv[2])
    else:
        main()
