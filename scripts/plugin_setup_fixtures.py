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
        marker = Path(os.environ["FIXTURE_OUTPUT_MARKER_FILE"]).read_bytes()
        sys.stdout.buffer.write(marker)
        sys.stderr.buffer.write(marker)
        sys.exit(2)
    if name in ("python3", "python"):
        mode = os.environ["FIXTURE_PYTHON_MODE"]
        if name == "python3":
            if mode == "stub":
                return  # An alias stub can exit zero without running Python.
            sys.exit(1)  # Simulate a Python version below 3.11.
        forward_runtime(args)
    if name == "uv":
        assert args[:5] == ["run", "--no-project", "--python", ">=3.11", "python"]
        forward_runtime(args[5:])
    if name == "uvx":
        return
    if name == "claude":
        fake_claude(args)
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


def forward_runtime(args):
    # Windows execv exits the launcher with zero and does not quote spaced args.
    # Wait for the real interpreter and propagate its status and byte streams.
    sys.exit(
        subprocess.run(
            [sys.executable, *args], stdin=sys.stdin.buffer, stdout=sys.stdout.buffer, stderr=sys.stderr.buffer
        ).returncode
    )


def fake_claude(args):
    """Model `claude plugin list/configure`: options in settings.json, keychain_values in a fake keychain."""
    root = Path(os.environ["FIXTURE_PLUGIN_ROOT"])
    plugin_id = root.name + "@fixture-market"
    config = Path(os.environ["CLAUDE_CONFIG_DIR"])
    settings_path, keychain_path = config / "settings.json", config / "fake-keychain.json"
    if args[:3] == ["plugin", "list", "--json"]:
        print(json.dumps([{"id": plugin_id, "installPath": str(root), "scope": "user"}]))
        return
    if args[:2] != ["plugin", "configure"] or args[2] != plugin_id:
        sys.exit(1)
    schema = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["userConfig"]
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    keychain = json.loads(keychain_path.read_text(encoding="utf-8")) if keychain_path.exists() else {}
    options = settings.setdefault("pluginConfigs", {}).setdefault(plugin_id, {}).setdefault("options", {})
    keychain_values = keychain.setdefault(plugin_id, {})
    if args[3:] == ["--json"]:
        inputs, configured = {}, []
        for key, entry in schema.items():
            value = keychain_values.get(key, "") if entry.get("sensitive") else options.get(key)
            if value not in (None, ""):
                configured.append(key)
            if entry.get("sensitive"):
                inputs[key] = ""  # Claude never reveals keychain values.
            elif value is None:
                default = entry.get("default")
                # Claude reports a boolean or choice default, but an unset number as "".
                inputs[key] = "" if default is None or entry["type"] == "number" else str(default).lower()
            else:
                inputs[key] = str(value).lower() if isinstance(value, bool) else str(value)
        print(json.dumps({"pluginId": plugin_id, "schema": schema, "inputs": inputs, "configured": configured}))
        return
    if args[3:] != ["--values-stdin"]:
        sys.exit(1)
    values = json.loads(sys.stdin.read())
    if os.environ.get("FIXTURE_FAIL") == "register":
        print(os.environ["FIXTURE_SECRET"])
        print(os.environ["FIXTURE_SECRET"], file=sys.stderr)
        sys.exit(2)
    for key, value in values.items():
        entry = schema.get(key)
        valid = isinstance(entry, dict) and isinstance(value, str) and "\n" not in value
        if valid and value and entry["type"] == "boolean":
            valid = value in ("true", "false")
        if valid and value and entry["type"] == "number":
            valid = value.isdigit() and entry.get("min", 0) <= int(value) <= entry.get("max", int(value))
        if valid and value and entry.get("options"):
            valid = value in entry["options"]
        if not valid:
            sys.exit(1)  # Claude validates every value before writing any of them.
    # Report success without retaining the values once; the restore write then succeeds.
    corrupt = os.environ.get("FIXTURE_FAIL") == "validate" and not (config / "not-retained").exists()
    for key, value in values.items():
        entry = schema[key]
        if corrupt and not entry.get("sensitive"):
            (config / "not-retained").touch()
            value = value + "-not-retained"
        if entry.get("sensitive"):
            if value:
                keychain_values[key] = value
            else:
                keychain_values.pop(key, None)
        elif entry["type"] == "boolean" and value in ("true", "false"):
            options[key] = value == "true"
        elif entry["type"] == "number" and value.isdigit():
            options[key] = int(value)
        else:
            options[key] = value
    config.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    keychain_path.write_text(json.dumps(keychain), encoding="utf-8")


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


def client_executable(directory, name):
    executable(
        directory,
        name,
        "import runpy,sys\nsys.argv=["
        + repr(str(Path(__file__).resolve()))
        + ", '--fake-client', "
        + repr(name)
        + "]+sys.argv[1:]\nrunpy.run_path(sys.argv[0],run_name='__main__')\n",
    )


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
        self.check_runtime_forwarding()
        for product in ("network", "protect", "access"):
            self.claude_scenario(product)
            for target in ("codex", "openclaw"):
                self.scenario(product, target)

    def check_runtime_forwarding(self):
        marker = b"FAKE-runtime-input\x00\xce\xa9\xf0\x9f\x98\x80\r\n"
        for name, prefix in (("python", []), ("uv", ["run", "--no-project", "--python", ">=3.11", "python"])):
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--fake-client",
                    name,
                    *prefix,
                    "-c",
                    "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); "
                    "sys.stderr.buffer.write(sys.argv[1].encode('utf-8')); sys.exit(23)",
                    'FAKE spaced "argument" \\ tail',
                ],
                env=dict(os.environ, FIXTURE_ARGV=str(self.root / "runtime-argv.jsonl"), FIXTURE_PYTHON_MODE="second"),
                input=marker,
                capture_output=True,
                timeout=30,
            )
            self.check(result.returncode == 23, "fake runtime propagates failing child status")
            self.check(result.stdout == marker, "fake runtime preserves stdin bytes")
            self.check(result.stderr == b'FAKE spaced "argument" \\ tail', "fake runtime preserves quoted arguments")

    def claude_scenario(self, product):
        """Claude Code: options through the fake CLI, legacy project settings migration."""
        upper = product.upper()
        plugin = self.repo / f"plugins/unifi-{product}"
        scripts = plugin / "scripts"
        plugin_id = f"unifi-{product}@fixture-market"
        workspace = self.root / (product + "-claude")
        bindir = workspace / "bin"
        bindir.mkdir(parents=True)
        for name in ("uvx", "claude"):
            client_executable(bindir, name)
        executable(bindir, "fixture-provider", "pass\n")
        config = workspace / "claude"
        config.mkdir()
        sample_value = 'FAKE-only "quotes" $dollar \\ slash spaces Ω 😀'
        environment = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_")}
        environment.update(
            HOME=str(workspace),
            USERPROFILE=str(workspace),
            CLAUDE_CONFIG_DIR=str(config),
            PATH=str(bindir) + os.pathsep + os.environ["PATH"],
            FIXTURE_ARGV=str(workspace / "argv.jsonl"),
            FIXTURE_SECRET=sample_value,
            FIXTURE_PLUGIN_ROOT=str(plugin),
        )
        base = f"UNIFI_{upper}_PASSWORD"
        settings_path, keychain_path = config / "settings.json", config / "fake-keychain.json"
        project = workspace / "project"
        (project / ".claude").mkdir(parents=True)
        legacy_path = project / ".claude/settings.local.json"

        def wrapper(name, *flags):
            if self.powershell:
                return [
                    self.powershell,
                    *("-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"),
                    str(scripts / (name + ".ps1")),
                    "-Target",
                    "claude",
                    *flags,
                ]
            return [self.shell, str(scripts / (name + ".sh")), "--target", "claude", *flags]

        def seed():
            settings_path.write_text(
                json.dumps(
                    {
                        "permissions": {"allow": ['Bash(grep "x{2,}")']},
                        "pluginConfigs": {
                            "other@market": {"options": {"keep": "yes"}},
                            plugin_id: {"options": {"host": "192.0.2.1"}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            keychain_path.unlink(missing_ok=True)

        def state():
            return (
                settings_path.read_bytes(),
                keychain_path.read_bytes() if keychain_path.exists() else None,
                legacy_path.read_bytes() if legacy_path.exists() else None,
            )

        def options():
            saved = json.loads(settings_path.read_text(encoding="utf-8"))["pluginConfigs"][plugin_id]["options"]
            keychain = json.loads(keychain_path.read_text(encoding="utf-8")) if keychain_path.exists() else {}
            return dict(saved, **keychain.get(plugin_id, {}))

        def run(command, patch=None, expected=0, extra=None):
            result = subprocess.run(
                command,
                input=b"" if patch is None else patch if isinstance(patch, bytes) else json.dumps(patch).encode(),
                cwd=project,
                env=dict(environment, **(extra or {})),
                capture_output=True,
                timeout=60,
            )
            if os.environ.get("FIXTURE_DEBUG") and (result.returncode == 0) != (expected == 0):
                print(command, result.stdout, result.stderr.replace(sample_value.encode(), b"<secret>"))
            self.check(result.returncode == expected if expected == 0 else result.returncode != 0, "setup exit status")
            self.check(sample_value.encode() not in result.stdout + result.stderr, "no secret in stdout/stderr")
            argv_path = workspace / "argv.jsonl"
            if argv_path.exists():
                self.check(sample_value not in argv_path.read_text(encoding="utf-8"), "no secret in client argv")
            return result

        def invoke(patch, expected=0, extra=None):
            return run(wrapper("set-env", "-InputJson" if self.powershell else "--input-json"), patch, expected, extra)

        def migrate(expected=0, extra=None):
            return run(wrapper("set-env", "-Migrate" if self.powershell else "--migrate"), None, expected, extra)

        seed()
        before = state()
        # Python resolution: a local interpreter first, managed Python through uv otherwise.
        runtime_bin = workspace / "runtime-bin"
        runtime_bin.mkdir()
        for name in ("uv", "uvx", "claude"):
            client_executable(runtime_bin, name)
        if os.name != "nt":
            (runtime_bin / "dirname").symlink_to(shutil.which("dirname"))
        runtime_environment = {"PATH": str(runtime_bin)}
        for mode in ("old", "missing", "stub", "second"):
            for name in ("python3", "python"):
                (runtime_bin / (name + (".cmd" if os.name == "nt" else ""))).unlink(missing_ok=True)
            if mode != "missing":
                client_executable(runtime_bin, "python3")
            if mode == "second":
                client_executable(runtime_bin, "python")
            runtime_environment["FIXTURE_PYTHON_MODE"] = mode
            invoke({base: sample_value}, extra=runtime_environment)
            self.check(options()["password"] == sample_value, mode + " Python resolution preserves stdin exactly")
            checked = run(wrapper("check-prereqs"), extra=runtime_environment)
            self.check(b"Prerequisites passed" in checked.stdout, mode + " Python prerequisite resolution")
            seed()
        invoke(b"{ malformed JSON patch", 1)
        self.check(state() == before, "malformed stdin JSON preserves prior options")
        for patch in (
            {"bad-key": sample_value},
            {base + "_VAULT": sample_value},
            {base + "_FILE": "relative"},
            {base + "_COMMAND": "./relative"},
            {base + "_COMMAND": "nonexistent-fixture-provider-command"},
            {base + "_FILE": str(workspace / "missing-credential")},
            {base: sample_value, base + "_FILE": str(workspace / "credential")},
            {base: [sample_value]},
            {base: sample_value + "\nsecond line"},
            {f"UNIFI_POLICY_{upper}_CAMERAS_UPDATE": "true", base: sample_value},
            {"UNIFI_PASSWORD_FILE": str(workspace / "credential")},
            {f"UNIFI_POLICY_{upper}_CREATE": "maybe"},
            {f"UNIFI_{upper}_PORT": "70000"},
            {f"UNIFI_{upper}_TOOL_PERMISSION_MODE": "always"},
        ):
            invoke(patch, 1)
            self.check(state() == before, "invalid key/provider/type/option preserved prior options")
        unsupported = invoke({f"UNIFI_POLICY_{upper}_CAMERAS_UPDATE": "true"}, 1)
        if not self.powershell:
            self.check(b"per-category policy overrides" in unsupported.stderr, "per-category override names the limit")
        # Missing dependencies and a failing client leave Claude's options untouched.
        isolated = workspace / "isolated"
        isolated.mkdir()
        if os.name == "nt":
            isolated_path = str(isolated) + os.pathsep + str(Path(sys.executable).parent)
        else:
            (isolated / "python3").symlink_to(sys.executable)
            (isolated / "dirname").symlink_to(shutil.which("dirname"))
            isolated_path = str(isolated)
        invoke({base: sample_value}, 1, {"PATH": isolated_path})
        self.check(state() == before, "missing uvx preserves options")
        client_executable(isolated, "uvx")
        invoke({base: sample_value}, 1, {"PATH": isolated_path})
        self.check(state() == before, "missing Claude CLI preserves options")
        invoke({base: sample_value}, 1, {"FIXTURE_FAIL": "register"})
        self.check(state() == before, "failed Claude configure preserves options")
        invoke({f"UNIFI_{upper}_USERNAME": "fixture-user", base: sample_value}, 1, {"FIXTURE_FAIL": "validate"})
        self.check(
            options().get("host") == "192.0.2.1" and options().get("username") in (None, ""),
            "unretained options are restored",
        )
        seed()
        invoke({base: sample_value})
        saved = options()
        self.check(saved["password"] == sample_value, "special characters round-trip through stdin to the keychain")
        self.check(saved["host"] == "192.0.2.1", "unrelated options preserved")
        other = json.loads(settings_path.read_text(encoding="utf-8"))
        self.check(
            other["pluginConfigs"]["other@market"] == {"options": {"keep": "yes"}} and "permissions" in other,
            "other plugins and settings preserved",
        )
        baseline_output = invoke({base: "FAKE-baseline-output"})
        for small in ("x", "true", "1234"):
            result = invoke({base: small})
            self.check(
                (result.stdout, result.stderr) == (baseline_output.stdout, baseline_output.stderr),
                "output is invariant even for short/boolean-like credentials",
            )
        # Provider switching clears the sibling options, keychain included.
        filename = str(workspace / "credential-Ω")
        Path(filename).write_text("FAKE-file-provider", encoding="utf-8")
        invoke({base + "_FILE": filename})
        saved = options()
        self.check("password" not in saved and saved["password_file"] == filename, "keychain-to-file switching")
        invoke({base + "_COMMAND": "fixture-provider --no-prompt"})
        saved = options()
        self.check(
            saved["password_file"] == "" and saved["password_command"] == "fixture-provider --no-prompt",
            "file-to-command switching",
        )
        invoke({base + "_COMMAND": None})
        self.check(options()["password_command"] == "", "null provider deletion")
        # Safety options default closed and a null deletion restores the default.
        invoke({f"UNIFI_POLICY_{upper}_CREATE": "TRUE", f"UNIFI_{upper}_TOOL_PERMISSION_MODE": "bypass"})
        self.check(options()["policy_create"] is True and options()["permission_mode"] == "bypass", "safety options")
        invoke({f"UNIFI_POLICY_{upper}_CREATE": None, f"UNIFI_{upper}_TOOL_PERMISSION_MODE": None})
        self.check(
            options()["policy_create"] is False and options()["permission_mode"] == "confirm",
            "deleting a safety option restores its safe default",
        )
        dry = run(
            wrapper(
                "set-env",
                "-DryRun" if self.powershell else "--dry-run",
                *(["-InputJson"] if self.powershell else ["--input-json"]),
            ),
            {base: sample_value},
        )
        self.check(b"dry run" in dry.stdout and options().get("password") is None, "dry run saves nothing")
        # Projects configured by earlier plugin versions.
        provider = workspace / "legacy-provider"
        provider.write_text("FAKE-legacy-provider", encoding="utf-8")
        other_product = "PROTECT" if upper != "PROTECT" else "ACCESS"
        legacy = {
            "permissions": {"allow": ["Bash(ls)"]},
            "env": {
                f"UNIFI_{upper}_HOST": "192.0.2.50",
                f"UNIFI_{upper}_USERNAME": "legacy-user",
                f"{base}_FILE": str(provider),
                f"UNIFI_POLICY_{upper}_UPDATE": "true",
                f"UNIFI_POLICY_{upper}_CAMERAS_UPDATE": "true",
                "UNIFI_TOOL_PERMISSION_MODE": "confirm",
                f"UNIFI_{other_product}_HOST": "192.0.2.60",
                "KEEP": "unrelated",
            },
        }
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
        legacy_bytes = legacy_path.read_bytes()
        noticed = invoke({f"UNIFI_{upper}_PORT": "8443"})
        self.check(b"--migrate" in noticed.stdout or b"-Migrate" in noticed.stdout, "setup names the migration")
        self.check(b"192.0.2.50" not in noticed.stdout and b"legacy-user" not in noticed.stdout, "notice omits values")
        self.check(legacy_path.read_bytes() == legacy_bytes, "ordinary setup leaves legacy project settings")
        checked = run(wrapper("check-prereqs"))
        self.check(b"--migrate" in checked.stdout, "prerequisite check names the migration")
        hook = scripts / "claude-session-check.sh"
        if os.name != "nt":
            notice = subprocess.run(
                ["sh", str(hook), product], env=dict(environment, CLAUDE_PROJECT_DIR=str(project)), capture_output=True
            )
            message = json.loads(notice.stdout)
            self.check("--migrate" in message["systemMessage"], "session notice names the migration")
            self.check(b"192.0.2.50" not in notice.stdout, "session notice omits values")
            quiet = subprocess.run(
                ["sh", str(hook), product],
                env=dict(environment, CLAUDE_PROJECT_DIR=str(project), CLAUDE_PLUGIN_OPTION_HOST="x"),
                capture_output=True,
            )
            self.check(quiet.stdout == b"" and quiet.returncode == 0, "configured plugin prints no notice")
        snapshot = state()
        migrate(1, {"FIXTURE_FAIL": "register"})
        self.check(state() == snapshot, "failed migration preserves options and project settings")
        provider.rename(workspace / "moved-provider")
        migrate(1)
        self.check(state() == snapshot, "migration validates legacy providers before writing")
        (workspace / "moved-provider").rename(provider)
        result = migrate()
        saved = options()
        self.check(
            saved["host"] == "192.0.2.50"
            and saved["username"] == "legacy-user"
            and saved["password_file"] == str(provider)
            and saved["policy_update"] is True
            and saved["port"] == 8443,
            "legacy settings migrate into options over earlier values",
        )
        remaining = json.loads(legacy_path.read_text(encoding="utf-8"))
        self.check(
            remaining["permissions"] == legacy["permissions"]
            and set(remaining["env"]) == {"UNIFI_TOOL_PERMISSION_MODE", f"UNIFI_{other_product}_HOST", "KEEP"},
            "migration removes only this plugin's legacy variables",
        )
        self.check(
            b"192.0.2.50" not in result.stdout + result.stderr and str(provider).encode() not in result.stdout,
            "migration output omits values",
        )
        self.check(f"UNIFI_POLICY_{upper}_CAMERAS_UPDATE".encode() in result.stdout, "dropped override is reported")
        migrate(1)
        # Interrupt at the project-settings replacement after options are saved.
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
        injection = workspace / "injection"
        injection.mkdir()
        (injection / "sitecustomize.py").write_text(
            "import os,time\nfrom pathlib import Path\n"
            "def replace(src,dst):\n"
            ' Path(os.environ["FIXTURE_READY"]).write_text(str(os.getpid()))\n'
            " while True: time.sleep(.02)\n"
            "os.replace=replace\n",
            encoding="utf-8",
        )
        marker = workspace / "ready"
        legacy_bytes = legacy_path.read_bytes()
        process = subprocess.Popen(
            wrapper("set-env", "-Migrate" if self.powershell else "--migrate"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=project,
            env=dict(environment, PYTHONPATH=str(injection), FIXTURE_READY=str(marker)),
        )
        try:
            deadline = time.monotonic() + 30
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.check(marker.exists(), "interruption reached project settings replacement")
            if self.powershell and os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
            elif self.powershell:
                os.kill(int(marker.read_text()), signal.SIGTERM)
            else:
                process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=20)
            self.check(process.returncode != 0, "interrupted migration exits nonzero")
            self.check(legacy_path.read_bytes() == legacy_bytes, "interrupted migration leaves project settings intact")
            self.check(sample_value.encode() not in stdout + stderr, "interrupted output omits secret")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        leftovers = [p.name for p in (project / ".claude").iterdir() if p.name.startswith(".unifi-setup-")]
        self.check(not leftovers, "no staging directory left after interruption")
        print(f"  [OK] {product}/claude: options, failures, provider switching, migration, interruption, argv privacy")

    def scenario(self, product, target):
        workspace = self.root / (product + "-" + target)
        workspace.mkdir()
        bindir = workspace / "bin"
        bindir.mkdir()
        for name in ("uvx", "codex", "openclaw"):
            client_executable(bindir, name)
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
        sample_value = 'FAKE-only "quotes" $dollar \\ slash spaces Ω 😀'
        output_marker = workspace / "client-output-marker"
        output_marker.write_bytes(sample_value.encode("utf-8"))
        environment["FIXTURE_OUTPUT_MARKER_FILE"] = str(output_marker)
        # Prove that both failing client operations emit the full UTF-8 marker,
        # even on Windows where text stdout can use a legacy code page.
        for operation in ("register", "validate"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--fake-client",
                    "codex",
                    "mcp",
                    "add" if operation == "register" else "get",
                ],
                env=dict(environment, FIXTURE_FAIL=operation),
                capture_output=True,
                timeout=30,
            )
            self.check(result.returncode == 2, "fake client fails the selected operation")
            self.check(result.stdout == output_marker.read_bytes(), "fake client emits output marker on stdout")
            self.check(result.stderr == output_marker.read_bytes(), "fake client emits output marker on stderr")
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
            self.check(sample_value.encode() not in result.stdout + result.stderr, "no secret in stdout/stderr")
            argv_path = workspace / "argv.jsonl"
            if argv_path.exists():
                self.check(sample_value not in argv_path.read_text(encoding="utf-8"), "no secret in client argv")
            return result

        seed()
        before = path.read_bytes()
        # Exercise the Windows write-access requirement for fsync on POSIX too.
        sync_injection = workspace / "sync-injection"
        sync_injection.mkdir()
        (sync_injection / "sitecustomize.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "real_fsync = os.fsync\n"
            "def fsync(fd):\n"
            " if os.name != 'nt':\n"
            "  import fcntl\n"
            "  if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY:\n"
            "   raise OSError('Fixture flush requires a writable descriptor')\n"
            " if os.environ.get('FIXTURE_FSYNC_FAIL'): raise OSError('Fixture flush failure')\n"
            " real_fsync(fd)\n"
            " Path(os.environ['FIXTURE_FSYNC_PATH']).write_text('flushed')\n"
            "os.fsync = fsync\n",
            encoding="utf-8",
        )
        sync_marker = workspace / "flushed"
        sync_environment = {"PYTHONPATH": str(sync_injection), "FIXTURE_FSYNC_PATH": str(sync_marker)}
        invoke({base: sample_value}, extra=sync_environment)
        self.check(sync_marker.read_text() == "flushed", "staged configuration flushed through writable descriptor")
        self.check(get_env(load())[base] == sample_value, "durable save preserves stdin exactly")
        seed()
        invoke({base: sample_value}, 1, dict(sync_environment, FIXTURE_FSYNC_FAIL="1"))
        self.check(path.read_bytes() == before, "failed flush preserves exact prior configuration")
        # No real uv invocation or download: PATH contains only fixture launchers.
        runtime_bin = workspace / "runtime-bin"
        runtime_bin.mkdir()
        for name in ("uv", "uvx", "codex", "openclaw"):
            client_executable(runtime_bin, name)
        if os.name != "nt":
            (runtime_bin / "dirname").symlink_to(shutil.which("dirname"))
        runtime_environment = {"PATH": str(runtime_bin)}
        prerequisite = [
            self.powershell or self.shell,
            *(
                ["-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
                if self.powershell
                else []
            ),
            str(scripts / ("check-prereqs.ps1" if self.powershell else "check-prereqs.sh")),
            "-Target" if self.powershell else "--target",
            target,
        ]
        for mode in ("old", "missing", "stub", "second"):
            for name in ("python3", "python"):
                candidate = runtime_bin / (name + (".cmd" if os.name == "nt" else ""))
                candidate.unlink(missing_ok=True)
            if mode != "missing":
                client_executable(runtime_bin, "python3")
            if mode == "second":
                client_executable(runtime_bin, "python")
            runtime_environment["FIXTURE_PYTHON_MODE"] = mode
            argv_path = workspace / "argv.jsonl"
            argv_path.unlink(missing_ok=True)
            invoke({base: sample_value}, extra=runtime_environment)
            self.check(get_env(load())[base] == sample_value, mode + " Python resolution preserves stdin exactly")
            checked = subprocess.run(
                prerequisite,
                cwd=workspace,
                env=dict(environment, **runtime_environment),
                capture_output=True,
                timeout=30,
            )
            self.check(checked.returncode == 0, mode + " Python prerequisite resolution")
            self.check(
                sample_value.encode() not in checked.stdout + checked.stderr,
                "runtime prerequisite output omits secrets",
            )
            calls = [json.loads(line) for line in argv_path.read_text(encoding="utf-8").splitlines()]
            managed = [call for call in calls if call[0] == "uv"]
            self.check(
                not managed if mode == "second" else len(managed) == 2,
                "local Python preference and managed Python fallback",
            )
            self.check(sample_value not in argv_path.read_text(encoding="utf-8"), "runtime argv omits secrets")
            seed()
        invoke(b"{ malformed JSON patch", 1)
        self.check(path.read_bytes() == before, "malformed stdin JSON preserves prior configuration")
        for malformed in (b"{ broken FAKE-only",):
            path.write_bytes(malformed)
            invoke({base: sample_value}, 1)
            self.check(path.read_bytes() == malformed, "invalid existing document preserved")
        seed()
        for patch in (
            {"bad-key": sample_value},
            {base + "_VAULT": sample_value},
            {base + "_FILE": "relative"},
            {base + "_COMMAND": "./relative"},
            {base + "_COMMAND": "nonexistent-fixture-provider-command"},
            {base + "_FILE": str(workspace / "missing-credential")},
            {base: sample_value, base + "_FILE": str(workspace / "credential")},
            {base: [sample_value]},
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
        invoke({base: sample_value}, 1, {"PATH": isolated_path})
        self.check(path.read_bytes() == before, "missing dependency preserves configuration")
        if not self.powershell and os.name != "nt":
            (isolated / "python3").unlink()
            invoke({base: sample_value}, 1, {"PATH": isolated_path})
            self.check(path.read_bytes() == before, "missing Python preserves configuration")
            (isolated / "python3").symlink_to(sys.executable)
        executable(isolated, "uvx", "pass\n")
        invoke({base: sample_value}, 1, {"PATH": isolated_path})
        self.check(path.read_bytes() == before, "missing client preserves registration")
        invoke({base: sample_value}, 1, {"FIXTURE_FAIL": "register"})
        self.check(path.read_bytes() == before, "failed client registration preserves exact registry bytes")
        invoke({base: sample_value}, 1, {"FIXTURE_FAIL": "validate"})
        self.check(path.read_bytes() == before, "failed client validation preserves exact registry bytes")
        invoke({base: sample_value})
        data = load()
        self.check(get_env(data)[base] == sample_value, "special characters round-trip")
        self.check(get_env(data)["KEEP"] == "old", "unrelated environment preserved")
        registry = data["mcp_servers"] if target == "codex" else data["mcp"]["servers"]
        original_registry = fixture["mcp_servers"] if target == "codex" else fixture["mcp"]["servers"]
        self.check(registry["unrelated"] == original_registry["unrelated"], "unrelated registration preserved")
        baseline_output = invoke({base: "FAKE-baseline-output"})
        for small in ("x", "true", "1234"):
            result = invoke({base: small})
            self.check(
                (result.stdout, result.stderr) == (baseline_output.stdout, baseline_output.stderr),
                "output is invariant even for short/boolean-like credentials",
            )
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
            for directory in (".codex-plugin", ".claude-plugin"):
                shutil.copytree(scripts.parent / directory, cached.parent / directory)
            for filename in (".mcp.json", ".mcp.codex.json"):
                source = scripts.parent / filename
                if source.exists():
                    shutil.copy2(source, cached.parent / filename)
            suffix = "set-env.ps1" if self.powershell else "set-env.sh"
            command[command.index(str(scripts / suffix))] = str(cached / suffix)
            invoke({f"UNIFI_{product.upper()}_HOST": "192.0.2.99"})
            self.check(
                get_env(load())[f"UNIFI_{product.upper()}_HOST"] == "192.0.2.99",
                "versioned plugin cache uses semantic server name",
            )
        if target == "codex":
            manifest = cached.parent / ".codex-plugin/plugin.json"
            manifest.parent.mkdir(exist_ok=True)
            manifest.write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            mcp = cached.parent / ".mcp.codex.json"
            mcp.write_text(
                json.dumps({"mcpServers": {f"unifi-{product}": {"args": [f"unifi-{product}-mcp==9.8.7"]}}}),
                encoding="utf-8",
            )
            refresh = command[:-1] + (["-Refresh"] if self.powershell else ["--refresh"])
            saved_env = get_env(load())
            result = subprocess.run(refresh, cwd=workspace, env=environment, capture_output=True, timeout=30)
            self.check(result.returncode == 0, "Codex refresh succeeds without credential input")
            self.check(get_env(load()) == saved_env, "Codex refresh preserves saved environment exactly")
            entry = load()["mcp_servers"][f"unifi-{product}"]
            self.check(entry["args"][-1] == f"unifi-{product}-mcp==9.8.7", "Codex refresh replaces stale package pin")
            self.check(b"9.8.7" in result.stdout, "Codex success prints pinned package version")
            self.check(
                "plugin 1.2.3; package unifi-" + product + "-mcp==9.8.7" in path.read_text(),
                "Codex records independent plugin and package versions",
            )
            before_refresh = path.read_bytes()
            failed = subprocess.run(
                refresh, cwd=workspace, env=dict(environment, FIXTURE_FAIL="validate"), capture_output=True, timeout=30
            )
            self.check(
                failed.returncode != 0 and path.read_bytes() == before_refresh,
                "failed Codex refresh preserves complete registration",
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
            {base: sample_value},
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
        process.stdin.write(json.dumps({base: sample_value}).encode())
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
            self.check(sample_value.encode() not in stdout + stderr, "interrupted output omits secret")
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
    with tempfile.TemporaryDirectory(prefix=".setup fixtures-", dir=repo) as temporary:
        fixtures = Fixtures(Path(temporary), args.shell, args.powershell)
        fixtures.run()
        print(f"Fixture assertions: {fixtures.passes} passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fake-client":
        fake_client(sys.argv[2])
    else:
        main()
