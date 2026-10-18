#!/usr/bin/env python3
"""Credential-free integration fixtures for the shell and PowerShell harnesses."""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import traceback
from pathlib import Path


class FixtureAssertionError(AssertionError):
    """An assertion with a fixture-authored label, never captured client output."""


def report_failure(error):
    # Exception messages, source lines and locals can contain captured credentials.
    # Keep the traceback locations and only our own fixed assertion labels.
    for frame in traceback.extract_tb(error.__traceback__):
        print(f"Fixture diagnostic: {Path(frame.filename).name}:{frame.lineno} in {frame.name}", file=sys.stderr)
    label = ": " + str(error) if isinstance(error, FixtureAssertionError) else ""
    print(f"Fixture failure: {type(error).__name__}{label}", file=sys.stderr)


def toml_literal(value):
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + "=" + toml_literal(v) for k, v in value.items()) + "}"
    return json.dumps(value, ensure_ascii=False)


def write_toml(path, document):
    lines = [
        json.dumps(k, ensure_ascii=False) + "=" + toml_literal(v) for k, v in document.items() if k != "mcp_servers"
    ]
    for name, entry in document.get("mcp_servers", {}).items():
        lines.append("[mcp_servers." + json.dumps(name, ensure_ascii=False) + "]")
        lines.extend(json.dumps(k, ensure_ascii=False) + "=" + toml_literal(v) for k, v in entry.items())
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
            separator = args.index("--")
            registry[args[2]] = {"command": args[separator + 1], "args": args[separator + 2 :]}
        elif args[:2] == ["mcp", "remove"]:
            registry.pop(args[2], None)
        elif args[:2] == ["mcp", "get"]:
            print(json.dumps({"transport": registry[args[2]]}))
            return
        write_toml(path, document)
    elif name == "openclaw":
        path = Path(os.environ["OPENCLAW_CONFIG_PATH"])
        document = json.loads(path.read_text(encoding="utf-8"))
        if args[:2] == ["mcp", "unset"]:
            if failure == "unset":
                marker = Path(os.environ["FIXTURE_OUTPUT_MARKER_FILE"]).read_bytes()
                sys.stdout.buffer.write(marker)
                sys.stderr.buffer.write(marker)
                sys.exit(2)
            servers = document["mcp"]["servers"]
            servers.pop(args[2])
            if failure == "overreach":
                servers.clear()  # An ill-behaved CLI that removes more than the named entry.
            # OpenClaw rewrites the whole document in its own layout.
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        else:
            sys.exit(1)


def forward_runtime(args):
    # Windows execv exits the launcher with zero and does not quote spaced args.
    # Wait for the real interpreter and propagate its status and byte streams.
    sys.exit(
        subprocess.run(
            [sys.executable, *args], stdin=sys.stdin.buffer, stdout=sys.stdout.buffer, stderr=sys.stderr.buffer
        ).returncode
    )


def fake_claude(args):
    """Model `claude plugin list/configure` as Claude Code 2.1.296 behaves.

    Options live in settings.json and sensitive values in a fake keychain, which keeps
    a value sent empty. FIXTURE_CLAUDE_VERSION and FIXTURE_CLAUDE_CLEARS model a later
    release, one that clears it.
    """
    if args == ["--version"]:
        print(os.environ.get("FIXTURE_CLAUDE_VERSION", "2.1.296 (Claude Code)"))
        return
    root = Path(os.environ["FIXTURE_PLUGIN_ROOT"])
    plugin_id = root.name + "@fixture-market"
    config = Path(os.environ["CLAUDE_CONFIG_DIR"])
    settings_path, keychain_path = config / "settings.json", config / "fake-keychain.json"
    if args[:3] == ["plugin", "list", "--json"]:
        print(json.dumps([{"id": plugin_id, "installPath": str(root), "scope": "user"}]))
        return
    if args[:2] != ["plugin", "configure"] or args[2] != plugin_id:
        sys.exit(1)
    # Client calls may block or be forcibly terminated. Retained project secrets
    # must stay in memory until replacement, with no settings copy here.
    assert not list((Path.cwd() / ".claude").glob(".unifi-setup-*")), "project settings staged during configure"
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
    # Claude consumes UTF-8 bytes; Windows Python text stdin uses a locale code page.
    values = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    if os.environ.get("FIXTURE_FAIL") == "register":
        marker = Path(os.environ["FIXTURE_OUTPUT_MARKER_FILE"]).read_bytes()
        sys.stdout.buffer.write(marker)
        sys.stderr.buffer.write(marker)
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
            elif os.environ.get("FIXTURE_CLAUDE_CLEARS"):
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


def setup_module(scripts):
    """Load a plugin's setup helper to reuse its entry layout, never to re-derive it."""
    spec = importlib.util.spec_from_file_location("fixture_setup_config", scripts / "setup_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
            raise FixtureAssertionError(label)
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
        self.check_failure_reporting()
        self.check_runtime_forwarding()
        for product in ("network", "protect", "access"):
            self.claude_scenario(product)
            for target in ("codex", "openclaw"):
                self.scenario(product, target)

    def check_failure_reporting(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            try:
                raise RuntimeError("FAKE-diagnostic-value")
            except RuntimeError as error:
                report_failure(error)
            try:
                self.check(False, 'comment # and quoted table "name"')
            except FixtureAssertionError as error:
                report_failure(error)
        diagnostic = output.getvalue()
        self.check("FAKE-diagnostic-value" not in diagnostic, "failure diagnostics omit exception text and source")
        self.check("in check_failure_reporting" in diagnostic, "failure diagnostics retain traceback locations")
        self.check(
            'Fixture failure: FixtureAssertionError: comment # and quoted table "name"' in diagnostic,
            "failure diagnostics retain assertion labels with punctuation",
        )

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
        output_marker = workspace / "client-output-marker"
        output_marker.write_bytes(sample_value.encode("utf-8"))
        environment = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_")}
        environment.update(
            HOME=str(workspace),
            USERPROFILE=str(workspace),
            CLAUDE_CONFIG_DIR=str(config),
            PATH=str(bindir) + os.pathsep + os.environ["PATH"],
            FIXTURE_ARGV=str(workspace / "argv.jsonl"),
            FIXTURE_OUTPUT_MARKER_FILE=str(output_marker),
            FIXTURE_PLUGIN_ROOT=str(plugin),
            # Windows Python pipes use the locale code page, unlike Claude's UTF-8 stdin.
            # Exercise that difference on every platform and Python resolution route.
            PYTHONIOENCODING="cp1252",
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
            self.check(result.returncode == expected if expected == 0 else result.returncode != 0, "setup exit status")
            self.check(sample_value.encode() not in result.stdout + result.stderr, "no secret in stdout/stderr")
            argv_path = workspace / "argv.jsonl"
            if argv_path.exists():
                self.check(sample_value not in argv_path.read_text(encoding="utf-8"), "no secret in client argv")
            return result

        def invoke(patch, expected=0, extra=None):
            return run(wrapper("set-env", "-InputJson" if self.powershell else "--input-json"), patch, expected, extra)

        def migrate(expected=0, extra=None, replace=False):
            flags = ["-Migrate" if self.powershell else "--migrate"]
            if replace:
                flags.append("-Replace" if self.powershell else "--replace")
            return run(wrapper("set-env", *flags), None, expected, extra)

        seed()
        # Model Claude's UTF-8 wire format independently of Python's text streams.
        # CRLF JSON whitespace must not affect the value saved in the fake keychain.
        wire = (
            json.dumps({"password": sample_value}, ensure_ascii=False, indent=2).replace("\n", "\r\n").encode("utf-8")
        )
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--fake-client",
            "claude",
            "plugin",
            "configure",
            plugin_id,
            "--values-stdin",
        ]
        result = subprocess.run(command, input=wire, env=environment, capture_output=True, timeout=30)
        self.check(result.returncode == 0, "fake Claude accepts UTF-8 JSON with legacy text streams")
        self.check(options()["password"] == sample_value, "fake Claude decodes stdin as UTF-8 exactly")
        result = subprocess.run(
            command, input=wire, env=dict(environment, FIXTURE_FAIL="register"), capture_output=True, timeout=30
        )
        self.check(result.returncode == 2, "fake Claude fails the selected operation")
        self.check(result.stdout == output_marker.read_bytes(), "fake Claude emits output marker on stdout")
        self.check(result.stderr == output_marker.read_bytes(), "fake Claude emits output marker on stderr")
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
            {"UNIFI_AUTO_CONFIRM": "false"},
            {f"UNIFI_POLICY_{upper}_CREATE": "maybe"},
            {f"UNIFI_{upper}_PORT": "70000"},
            {f"UNIFI_{upper}_TOOL_PERMISSION_MODE": "always"},
        ):
            invoke(patch, 1)
            self.check(state() == before, "invalid key/provider/type/option preserved prior options")
        unsupported = invoke({f"UNIFI_POLICY_{upper}_CAMERAS_UPDATE": "true"}, 1)
        deprecated = invoke({"UNIFI_AUTO_CONFIRM": "true"}, 1)
        if not self.powershell:
            self.check(b"per-category policy overrides" in unsupported.stderr, "per-category override names the limit")
            self.check(
                f"UNIFI_{upper}_TOOL_PERMISSION_MODE".encode() in deprecated.stderr,
                "deprecated auto-confirm points at the permission mode",
            )
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
        # Claude Code keeps a keychain-held secret sent an empty value, so every change
        # that would clear one is refused before any write, naming the working route.
        filename = str(workspace / "credential-Ω")
        Path(filename).write_text("FAKE-file-provider", encoding="utf-8")
        api_key = f"UNIFI_{upper}_API_KEY"
        invoke({f"UNIFI_{upper}_USERNAME": "fixture-user", api_key: "FAKE-api-key-value"})
        self.check(options()["password"] == "1234" and options()["api_key"] == "FAKE-api-key-value", "keychain seeded")

        def writes():
            lines = (workspace / "argv.jsonl").read_text(encoding="utf-8").splitlines()
            return sum("--values-stdin" in json.loads(line) for line in lines)

        def refused_clear(result, variable, other, label):
            message = result.stderr.decode("utf-8", "replace")
            self.check(
                variable in message
                and "cannot clear a saved secret" in message
                and f"claude plugin uninstall {plugin_id}" in message
                and f"claude plugin install {plugin_id}" in message,
                label + " names the variable and the uninstall route",
            )
            self.check(
                f"UNIFI_{upper}_HOST" in message and f"UNIFI_{upper}_USERNAME" in message and other in message,
                label + " names the options to set again",
            )
            self.check(
                all(value not in message for value in ("1234", "FAKE-api-key-value", "192.0.2.1", "fixture-user")),
                label + " omits values",
            )

        for variable, other in ((base, api_key), (api_key, base)):
            for patch in (
                {variable + "_FILE": filename},
                {variable + "_COMMAND": "fixture-provider --no-prompt"},
                {variable: None},
                {variable: None, variable + "_FILE": None, variable + "_COMMAND": None},
                {variable: ""},
            ):
                snapshot, count = state(), writes()
                result = invoke(patch, 1)
                self.check(state() == snapshot and writes() == count, "keychain clear refused before any write")
                refused_clear(result, variable, other, "keychain clear refusal")
        snapshot, count = state(), writes()
        result = run(
            wrapper(
                "set-env",
                "-DryRun" if self.powershell else "--dry-run",
                *(["-InputJson"] if self.powershell else ["--input-json"]),
            ),
            {base + "_FILE": filename},
            1,
        )
        self.check(state() == snapshot and writes() == count, "dry run refuses a keychain clear")
        # A release newer than the newest known one: clearing is tried alone first, so
        # one that ignores the empty value changes nothing, and one that honours it works.
        for variable, other in ((base, api_key), (api_key, base)):
            for version in ("2.2.0 (Claude Code)", "unrecognized"):
                snapshot, count = state(), writes()
                result = invoke({variable + "_FILE": filename}, 1, {"FIXTURE_CLAUDE_VERSION": version})
                self.check(state() == snapshot and writes() == count + 1, "a kept secret changes nothing")
                self.check(
                    b"kept " + variable.encode() + b" in the system keychain" in result.stderr
                    and b"No settings were changed" in result.stderr,
                    "the post-write refusal names the secret Claude Code kept",
                )
                refused_clear(result, variable, other, "kept secret refusal")
        newer = {"FIXTURE_CLAUDE_VERSION": "2.2.0 (Claude Code)", "FIXTURE_CLAUDE_CLEARS": "1"}
        count = writes()
        invoke({api_key + "_FILE": filename}, extra=newer)
        saved = options()
        self.check(
            "api_key" not in saved and saved["api_key_file"] == filename and saved["password"] == "1234",
            "a release that clears keychain values switches to a provider",
        )
        self.check(writes() == count + 2, "the keychain value is cleared alone, before the provider is saved")
        invoke({api_key + "_FILE": None})
        # Stand-in for uninstalling and reinstalling the plugin: every option cleared.
        seed()
        invoke({base + "_FILE": filename})
        saved = options()
        self.check("password" not in saved and saved["password_file"] == filename, "switching without a keychain value")
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
                f"UNIFI_{other_product}_PASSWORD": sample_value,
                "UNIFI_API_KEY": sample_value,
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
        self.check(
            b"--replace" in checked.stdout and f"UNIFI_{upper}_HOST".encode() in checked.stdout,
            "prerequisite check names settings that differ from the saved options",
        )
        self.check(b"192.0.2.50" not in checked.stdout and b"192.0.2.1" not in checked.stdout, "check omits values")
        self.check(b"no UniFi plugin settings remain" not in checked.stdout, "no shared-key notice while keys remain")
        hook = scripts / "claude-session-check.sh"
        if os.name != "nt":
            notice = subprocess.run(
                ["sh", str(hook), product], env=dict(environment, CLAUDE_PROJECT_DIR=str(project)), capture_output=True
            )
            message = json.loads(notice.stdout)
            self.check("--migrate" in message["systemMessage"], "session notice names the migration")
            self.check(b"192.0.2.50" not in notice.stdout, "session notice omits values")
            self.check(
                "starts unconfigured" in message["systemMessage"] and "shared UNIFI_" not in message["systemMessage"],
                "session notice says the server starts unconfigured when no shared keys exist",
            )
            shared_project = workspace / "shared-project"
            (shared_project / ".claude").mkdir(parents=True)
            (shared_project / ".claude/settings.local.json").write_text(
                json.dumps(
                    {
                        "env": {
                            f"UNIFI_{upper}_PORT": "8443",
                            "UNIFI_HOST": "192.0.2.80",
                            "UNIFI_USERNAME": "shared-user",
                        }
                    }
                ),
                encoding="utf-8",
            )
            shared_notice = subprocess.run(
                ["sh", str(hook), product],
                env=dict(environment, CLAUDE_PROJECT_DIR=str(shared_project)),
                capture_output=True,
            )
            shared_message = json.loads(shared_notice.stdout)
            for text in (shared_message["systemMessage"], shared_message["hookSpecificOutput"]["additionalContext"]):
                self.check(
                    "shared UNIFI_" in text and "different controller" in text and "unconfigured" not in text,
                    "session notice says shared keys are used when they exist",
                )
            self.check("--migrate" in shared_message["systemMessage"], "shared-key notice still names the migration")
            self.check(
                b"192.0.2.80" not in shared_notice.stdout and b"shared-user" not in shared_notice.stdout,
                "shared-key notice omits values",
            )
            elsewhere = subprocess.run(
                ["sh", str(hook), product],
                env=dict(environment, CLAUDE_PROJECT_DIR=str(project), CLAUDE_PLUGIN_OPTION_HOST="x"),
                capture_output=True,
            )
            other_message = json.loads(elsewhere.stdout)
            for text in (other_message["systemMessage"], other_message["hookSpecificOutput"]["additionalContext"]):
                self.check(
                    "another project" in text and "--replace" in text and "every project" in text,
                    "configured plugin still notices this project's own legacy settings",
                )
            self.check("remove the leftover" in other_message["systemMessage"], "notice names the removal choice")
            for text in (other_message["systemMessage"], message["systemMessage"]):
                self.check(
                    "/reload-plugins or start a new session" in text
                    and "/mcp reconnect" in text
                    and "only if /mcp shows the server as failed" in text,
                    "notices name reload as the recovery and reconnect only for a failed server",
                )
            self.check(b"192.0.2.50" not in elsewhere.stdout, "other-project notice omits values")
            for quiet_env in (
                dict(
                    environment, CLAUDE_PROJECT_DIR=str(shared_project.parent / "absent"), CLAUDE_PLUGIN_OPTION_HOST="x"
                ),
                dict(environment, CLAUDE_PROJECT_DIR=str(workspace / "no-project")),
            ):
                quiet = subprocess.run(["sh", str(hook), product], env=quiet_env, capture_output=True)
                self.check(quiet.stdout == b"" and quiet.returncode == 0, "no legacy settings print no notice")
            only_shared = workspace / "only-shared"
            (only_shared / ".claude").mkdir(parents=True)
            (only_shared / ".claude/settings.local.json").write_text(
                json.dumps({"env": {"UNIFI_HOST": "192.0.2.80"}}), encoding="utf-8"
            )
            quiet = subprocess.run(
                ["sh", str(hook), product],
                env=dict(environment, CLAUDE_PROJECT_DIR=str(only_shared), CLAUDE_PLUGIN_OPTION_HOST="x"),
                capture_output=True,
            )
            self.check(quiet.stdout == b"" and quiet.returncode == 0, "configured plugin ignores shared-only settings")
            self.check_same_connection_notice(hook, product, workspace, environment)
        # Migrating a provider over a keychain-held password is refused before any write,
        # with or without --replace.
        invoke({base: "FAKE-keychain-password"})
        same_host = json.dumps({"env": {f"UNIFI_{upper}_HOST": "192.0.2.1", f"{base}_FILE": str(provider)}})
        for text, replace in ((same_host, False), (legacy_bytes.decode("utf-8"), True)):
            legacy_path.write_text(text, encoding="utf-8")
            snapshot, count = state(), writes()
            result = migrate(1, replace=replace)
            self.check(state() == snapshot and writes() == count, "migration refuses a keychain clear before writing")
            self.check(
                base.encode() in result.stderr and b"claude plugin uninstall" in result.stderr,
                "migration refusal names the variable and the uninstall route",
            )
        legacy_path.write_bytes(legacy_bytes)
        keychain_path.unlink()
        snapshot = state()
        migrate(1, {"FIXTURE_FAIL": "register"})
        self.check(state() == snapshot, "failed migration preserves options and project settings")
        provider.rename(workspace / "moved-provider")
        migrate(1)
        self.check(state() == snapshot, "migration validates legacy providers before writing")
        (workspace / "moved-provider").rename(provider)
        run(
            wrapper(
                "set-env",
                "-Replace" if self.powershell else "--replace",
                *(["-InputJson"] if self.powershell else ["--input-json"]),
            ),
            {f"UNIFI_{upper}_PORT": "8443"},
            1,
        )
        self.check(state() == snapshot, "replace without migrate changes nothing")
        refused = migrate(1)
        self.check(state() == snapshot, "migration over differing saved options changes nothing")
        self.check(
            f"UNIFI_{upper}_HOST".encode() in refused.stderr and b"--replace" in refused.stderr,
            "differing saved options are named with the replace choice",
        )
        self.check(
            f"UNIFI_{upper}_USERNAME".encode() not in refused.stderr,
            "an option unset elsewhere is not reported as differing",
        )
        self.check(b"192.0.2.50" not in refused.stderr and b"192.0.2.1" not in refused.stderr, "refusal omits values")
        result = migrate(replace=True)
        self.check(b"Replaced the plugin options" in result.stdout, "replacement is reported")
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
            and set(remaining["env"])
            == {
                "UNIFI_TOOL_PERMISSION_MODE",
                f"UNIFI_{other_product}_HOST",
                f"UNIFI_{other_product}_PASSWORD",
                "UNIFI_API_KEY",
                "KEEP",
            },
            "migration removes only this plugin's legacy variables",
        )
        self.check(
            b"192.0.2.50" not in result.stdout + result.stderr and str(provider).encode() not in result.stdout,
            "migration output omits values",
        )
        self.check(f"UNIFI_POLICY_{upper}_CAMERAS_UPDATE".encode() in result.stdout, "dropped override is reported")
        self.check(
            f"UNIFI_{other_product}_HOST".encode() in result.stdout and b"UNIFI_API_KEY" in result.stdout,
            "kept shared settings are named with the other plugin settings that keep them",
        )
        migrate(1)
        # Interrupt before and after publication, with other/shared credentials
        # retained in the project settings. Windows must clean up without finally.
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
        injection = workspace / "injection"
        injection.mkdir()
        (injection / "sitecustomize.py").write_text(
            "import os,sys,time\nfrom pathlib import Path\n"
            "def boundary(frame,event,arg):\n"
            ' if (event == os.environ.get("FIXTURE_BOUNDARY", "call")\n'
            '     and frame.f_code.co_name == "publish_project_settings"):\n'
            '  if os.environ.get("FIXTURE_REPLACE_FAIL"): raise OSError("FAKE-only write failure")\n'
            '  Path(os.environ["FIXTURE_READY"]).write_text(str(os.getpid()))\n'
            "  while True: time.sleep(.02)\n"
            "sys.setprofile(boundary)\n",
            encoding="utf-8",
        )
        marker = workspace / "ready"
        legacy_bytes = legacy_path.read_bytes()
        migrate(1, {"PYTHONPATH": str(injection), "FIXTURE_REPLACE_FAIL": "1"})
        self.check(legacy_path.read_bytes() == legacy_bytes, "failed publication leaves project settings intact")
        self.check(not list(legacy_path.parent.glob(".unifi-setup-*")), "failed publication leaves no secret copy")
        for boundary in ("call", "return"):
            marker.unlink(missing_ok=True)
            legacy_path.write_bytes(legacy_bytes)
            process = subprocess.Popen(
                wrapper("set-env", "-Migrate" if self.powershell else "--migrate"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=project,
                env=dict(environment, PYTHONPATH=str(injection), FIXTURE_READY=str(marker), FIXTURE_BOUNDARY=boundary),
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
                if boundary == "call":
                    self.check(
                        legacy_path.read_bytes() == legacy_bytes, "interrupted migration leaves project settings intact"
                    )
                else:
                    self.check(
                        json.loads(legacy_path.read_bytes()) == remaining,
                        "published settings survive interruption and handle closure",
                    )
                self.check(sample_value.encode() not in stdout + stderr, "interrupted output omits secret")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            leftovers = [p.name for p in (project / ".claude").iterdir() if p.name.startswith(".unifi-setup-")]
            self.check(not leftovers, "no staging directory left after interruption")
            artifacts = list(legacy_path.parent.glob(".unifi-setup-*"))
            self.check(not artifacts, "interrupted migration leaves no files containing retained secrets")
            if boundary == "call":
                migrate()
            self.check(json.loads(legacy_path.read_bytes()) == remaining, "retry preserves complete migrated settings")
            remaining_env = json.loads(legacy_path.read_text(encoding="utf-8"))["env"]
            self.check(
                remaining_env[f"UNIFI_{other_product}_PASSWORD"] == sample_value, "retry preserves other plugin secret"
            )
            self.check(remaining_env["UNIFI_API_KEY"] == sample_value, "retry preserves shared secret")
            self.check(not list(legacy_path.parent.glob(".unifi-setup-*")), "retry leaves no replacement artifacts")
        # Another product can rely entirely on shared fallbacks, without leaving
        # any scoped keys to signal that its migration is still pending.
        shared_fallbacks = {
            "UNIFI_HOST": "192.0.2.80",
            "UNIFI_USERNAME": "legacy-shared-user",
            "UNIFI_PASSWORD_FILE": str(provider),
        }
        legacy_path.write_text(
            json.dumps({"env": {f"UNIFI_{upper}_HOST": "192.0.2.50", f"UNIFI_{upper}_USERNAME": "legacy-user"}}),
            encoding="utf-8",
        )
        result = migrate()
        self.check(
            b"Replaced" not in result.stdout and json.loads(legacy_path.read_text(encoding="utf-8"))["env"] == {},
            "identical saved options migrate without --replace",
        )
        legacy_path.write_text(
            json.dumps({"env": {f"UNIFI_{upper}_HOST": "192.0.2.70", **shared_fallbacks}}), encoding="utf-8"
        )
        result = migrate(replace=True)
        self.check(
            json.loads(legacy_path.read_text(encoding="utf-8"))["env"] == shared_fallbacks,
            "migration preserves credentials for shared-fallback-only consumers",
        )
        self.check(
            options()["host"] == "192.0.2.70"
            and options()["username"] == "legacy-shared-user"
            and options()["password_file"] == str(provider),
            "migration saves this plugin without deleting other consumers fallbacks",
        )
        self.check(
            all(key.encode() in result.stdout for key in shared_fallbacks)
            and b"other consumers have not been verified" in result.stdout,
            "retained shared keys name the missing consumer evidence",
        )
        leftover = run(wrapper("check-prereqs"))
        self.check(
            all(key.encode() in leftover.stdout for key in shared_fallbacks)
            and b"exports them into every process" in leftover.stdout,
            "prerequisite check names shared keys left after every plugin migrated",
        )
        self.check(
            b"192.0.2.80" not in leftover.stdout
            and b"legacy-shared-user" not in leftover.stdout
            and str(provider).encode() not in leftover.stdout,
            "shared-key notice omits values",
        )
        # An apparent last migration still cannot prove shared consumers migrated.
        last = {
            "permissions": legacy["permissions"],
            "env": {
                f"UNIFI_{upper}_HOST": "192.0.2.70",
                f"UNIFI_{upper}_USERNAME": "legacy-user",
                f"UNIFI_POLICY_{upper}_UPDATE": "true",
                "UNIFI_TOOL_PERMISSION_MODE": "confirm",
                "UNIFI_API_KEY": sample_value,
                "UNIFI_CUSTOM_FIXTURE": "kept",
                "KEEP": "unrelated",
            },
        }
        legacy_path.write_text(json.dumps(last), encoding="utf-8")
        result = migrate(replace=True)
        remaining_env = json.loads(legacy_path.read_text(encoding="utf-8"))["env"]
        self.check(
            remaining_env
            == {
                "UNIFI_TOOL_PERMISSION_MODE": "confirm",
                "UNIFI_API_KEY": sample_value,
                "UNIFI_CUSTOM_FIXTURE": "kept",
                "KEEP": "unrelated",
            },
            "the apparent last migration retains shared settings without consumer evidence",
        )
        self.check(options()["api_key"] == sample_value, "the shared credential reached the options")
        self.check(
            b"UNIFI_API_KEY" in result.stdout and b"UNIFI_CUSTOM_FIXTURE" in result.stdout, "removed names are reported"
        )
        self.check(b"other consumers have not been verified" in result.stdout, "consumer uncertainty is reported")
        leftover = run(wrapper("check-prereqs"))
        self.check(
            all(
                k.encode() in leftover.stdout
                for k in ("UNIFI_TOOL_PERMISSION_MODE", "UNIFI_API_KEY", "UNIFI_CUSTOM_FIXTURE")
            )
            and b"KEEP" not in leftover.stdout
            and sample_value.encode() not in leftover.stdout,
            "shared-key notice names only UNIFI_ keys, never values",
        )
        self.check(
            b"legacy-user" not in result.stdout and sample_value.encode() not in result.stdout, "values are omitted"
        )
        # A leftover deprecated UNIFI_AUTO_CONFIRM is named, called deprecated and kept, never valued.
        for value, effect in (("on", b"turns on bypass"), ("garbage-marker", b"no effect")):
            leftover = json.dumps({"env": {f"UNIFI_{upper}_PORT": "8443", "UNIFI_AUTO_CONFIRM": value}})
            for label, action in (
                ("setup", lambda: invoke({f"UNIFI_{upper}_PORT": "8443"})),
                ("check", lambda: run(wrapper("check-prereqs"))),
                ("migration", migrate),
            ):
                legacy_path.write_text(leftover, encoding="utf-8")
                result = action()
                output = result.stdout + result.stderr
                self.check(
                    b"UNIFI_AUTO_CONFIRM is deprecated" in result.stdout and effect in result.stdout,
                    f"{label} names the deprecated auto-confirm and what it does ({value})",
                )
                self.check(
                    effect == b"no effect" or b"UNIFI_TOOL_PERMISSION_MODE=bypass" in result.stdout,
                    f"{label} says what to set instead of a truthy auto-confirm",
                )
                self.check(
                    b"UNIFI_AUTO_CONFIRM=" not in output
                    and (value != "garbage-marker" or value.encode() not in output),
                    f"{label} omits the auto-confirm value",
                )
            self.check(
                json.loads(legacy_path.read_text(encoding="utf-8"))["env"] == {"UNIFI_AUTO_CONFIRM": value},
                "migration keeps the deprecated auto-confirm with the shared keys",
            )
        print(f"  [OK] {product}/claude: options, failures, provider switching, migration, interruption, argv privacy")

    def check_same_connection_notice(self, hook, product, workspace, environment):
        """A project whose leftover connection values equal the saved options gets the gentle notice."""
        upper = product.upper()
        same = workspace / "same-project"
        (same / ".claude").mkdir(parents=True)
        legacy = same / ".claude/settings.local.json"
        options = {
            "CLAUDE_PLUGIN_OPTION_HOST": "192.0.2.70",
            "CLAUDE_PLUGIN_OPTION_USERNAME": "same-user",
            "CLAUDE_PLUGIN_OPTION_PORT": "8443",
        }
        values = {
            f"UNIFI_{upper}_HOST": "192.0.2.70",
            f"UNIFI_{upper}_USERNAME": "same-user",
            f"UNIFI_{upper}_PORT": "08443",
            f"UNIFI_{upper}_PASSWORD_FILE": "/fixture/password-file",
        }
        if product == "network":
            # An empty site and an unset site option both mean the default site.
            values["UNIFI_NETWORK_SITE"] = ""

        def notice(env_values, extra, shell):
            legacy.write_text(json.dumps({"env": env_values}, indent="\t"), encoding="utf-8")
            result = subprocess.run(
                [shell, str(hook), product],
                env=dict(environment, CLAUDE_PROJECT_DIR=str(same), **extra),
                capture_output=True,
            )
            self.check(result.returncode == 0, "session notice exits cleanly")
            for value in (b"192.0.2.70", b"192.0.2.71", b"same-user", b"other-user", b"8443", b"/fixture/"):
                self.check(value not in result.stdout + result.stderr, "session notice omits values")
            message = json.loads(result.stdout)
            return message["systemMessage"] + "\n" + message["hookSpecificOutput"]["additionalContext"]

        def gentle(text):
            return "same controller" in text and "--migrate" in text and "another project" not in text

        for shell in dict.fromkeys(("sh", self.shell)):
            text = notice(values, options, shell)
            self.check(gentle(text) and "remove" in text.lower(), "matching leftover values get the gentle notice")
            self.check("--replace" not in text, "gentle notice does not offer replacement")
            port_default = dict(values, **{f"UNIFI_{upper}_PORT": "443"})
            unset_port = {k: v for k, v in options.items() if k != "CLAUDE_PLUGIN_OPTION_PORT"}
            self.check(gentle(notice(port_default, unset_port, shell)), "an unset port option means port 443")
            host_only = {f"UNIFI_{upper}_HOST": "192.0.2.70"}
            self.check(gentle(notice(host_only, options, shell)), "only values the project holds are compared")
            differing = (
                dict(values, **{f"UNIFI_{upper}_HOST": "192.0.2.71"}),
                dict(values, **{f"UNIFI_{upper}_USERNAME": "other-user"}),
                dict(values, **{f"UNIFI_{upper}_PORT": "8444"}),
                dict(values, **{f"UNIFI_{upper}_PORT": "port"}),
                dict(values, **{f"UNIFI_{upper}_USERNAME": "same-user\\"}),
                {k: v for k, v in values.items() if k != f"UNIFI_{upper}_HOST"},
            )
            for env_values in differing:
                text = notice(env_values, options, shell)
                self.check(
                    "another project" in text and not gentle(text), "differing leftover values keep the other notice"
                )
            unset_username = {k: v for k, v in options.items() if k != "CLAUDE_PLUGIN_OPTION_USERNAME"}
            self.check("another project" in notice(values, unset_username, shell), "an unset option differs")

            def named(text):
                return {field for field in ("HOST", "USERNAME", "PORT", "SITE") if f"UNIFI_{upper}_{field}" in text}

            self.check(
                named(notice(dict(values, **{f"UNIFI_{upper}_PORT": "8444"}), options, shell)) == {"PORT"},
                "a port-only difference names only the port variable",
            )
            self.check(
                named(notice(dict(values, **{f"UNIFI_{upper}_PORT": "port"}), options, shell)) == {"PORT"},
                "a port that is not a number is named",
            )
            self.check(
                named(notice(values, unset_username, shell)) == {"USERNAME"},
                "an unset option is named as the differing variable",
            )
            self.check(
                named(notice({k: v for k, v in values.items() if k != f"UNIFI_{upper}_HOST"}, options, shell))
                == {"HOST"},
                "a project without a host names the host variable",
            )
            several = dict(
                values,
                **{
                    f"UNIFI_{upper}_HOST": "192.0.2.71",
                    f"UNIFI_{upper}_USERNAME": "other-user",
                    f"UNIFI_{upper}_PORT": "8444",
                },
            )
            several_text = notice(several, options, shell)
            self.check(
                named(several_text) == {"HOST", "USERNAME", "PORT"}, "several differences name every differing variable"
            )
            self.check(
                f"UNIFI_{upper}_HOST, UNIFI_{upper}_USERNAME, UNIFI_{upper}_PORT" in several_text,
                "differing variables are listed in a fixed order",
            )
            if product == "network":
                site = dict(values, UNIFI_NETWORK_SITE="branch")
                self.check("another project" in notice(site, options, shell), "a differing site keeps the other notice")
                self.check(named(notice(site, options, shell)) == {"SITE"}, "a differing site is named alone")
                self.check(
                    gentle(notice(site, dict(options, CLAUDE_PLUGIN_OPTION_SITE="branch"), shell)),
                    "a matching site gets the gentle notice",
                )
            else:
                site = dict(values, **{f"UNIFI_{upper}_SITE": "branch"})
                self.check(gentle(notice(site, options, shell)), "a site without an option is not compared")

    def codex_conversion_scenario(self, workspace, environment, command, cached, path, product, setup):
        """Setup before plugin 1.0.0 saved a config.toml entry that shadows the bundled server; one refresh moves it."""
        name = f"unifi-{product}"
        upper = product.upper()
        config = workspace / "codex/config.toml"
        refresh = command[:-1] + (["-Refresh"] if self.powershell else ["--refresh"])
        prerequisite = [
            *(
                [self.powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
                if self.powershell
                else [self.shell]
            ),
            str(cached / ("check-prereqs.ps1" if self.powershell else "check-prereqs.sh")),
            *(["-Target", "codex"] if self.powershell else ["--target", "codex"]),
        ]
        secret = 'FAKE-only "quoted" $dollar \\ tab\there Ω'

        def run(argv, **extra):
            return subprocess.run(argv, cwd=workspace, env=dict(environment, **extra), capture_output=True, timeout=30)

        def backups():
            return sorted(config.parent.glob("config.toml.bak-*"))

        def start(text):
            path.unlink(missing_ok=True)
            for backup in backups():
                backup.unlink()
            config.write_bytes(text.encode("utf-8"))

        def private(file):
            return os.name == "nt" or file.stat().st_mode & 0o777 == 0o600

        def without_entry(document):
            return dict(document, mcp_servers=document.get("mcp_servers", {}))

        moved = {f"UNIFI_{upper}_HOST": "192.0.2.10", f"UNIFI_{upper}_PASSWORD": secret, "UNIFI_POLICY_CREATE": "false"}
        env_table = "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in moved.items())
        commented = (
            '# user note\nmodel = "fixture"  # trailing\n\n# my server\n[mcp_servers.unrelated]  # keep\n'
            'command = "keep"\n# inside\nenv = { KEEP = "yes" }\n\n'
            f"# unifi-plugin-setup: {name} plugin 0.0.1; package {name}-mcp==0.0.1\n"
            f'# note for the entry\n[mcp_servers."{name}"]\ncommand = "uvx"\n'
            f'args = ["--python-preference", "system", "{name}-mcp==0.0.1"]\nstartup_timeout_sec = 30\n\n'
            f'[mcp_servers."{name}".env]\n' + env_table + 'KEEP = "old"\n\n'
            '# about the next server\n[mcp_servers.after]\ncommand = "after"\n'
        )
        for eol in ("\n", "\r\n"):
            source = commented.replace("\n", eol)
            start(source)
            checked = run(prerequisite)
            self.check(
                checked.returncode == 0
                and b"takes precedence over the plugin's own server" in checked.stdout
                and (b"-Target codex -Refresh" if self.powershell else b"--target codex --refresh") in checked.stdout,
                "prerequisites name the shadowing entry and its one-time refresh",
            )
            result = run(refresh)
            self.check(result.returncode == 0, "refresh converts a shadowing entry without input")
            self.check(setup.read_settings(path) == moved, "conversion moves exactly the entry's UNIFI_ settings")
            self.check(private(path), "converted settings file is private (600)")
            text = config.read_bytes().decode("utf-8")
            prefix = commented.split(f"# unifi-plugin-setup: {name} ")[0] + "# note for the entry\n"
            suffix = '# about the next server\n[mcp_servers.after]\ncommand = "after"\n'
            self.check(
                text == (prefix + suffix).replace("\n", eol),
                "conversion leaves config.toml byte-identical apart from the entry",
            )
            [backup] = backups()
            self.check(backup.read_bytes() == source.encode("utf-8") and private(backup), "private exact backup")
            self.check(
                b"Not moved" in result.stdout and b"KEEP" in result.stdout and b"startup_timeout_sec" in result.stdout,
                "conversion names what it did not move",
            )
            self.check(secret.encode() not in result.stdout + result.stderr, "conversion output omits values")
            checked = run(prerequisite)
            self.check(checked.returncode == 0 and b"takes precedence" not in checked.stdout, "notice goes quiet")
            again = run(refresh)
            self.check(
                again.returncode == 0 and b"Nothing to convert" in again.stdout and len(backups()) == 1,
                "a second refresh changes nothing",
            )

        # Every TOML layout the editor understands keeps the rest of the document exactly.
        server_text = (
            f'[mcp_servers."{name}"]\ncommand = "uvx"\nargs = ["previous"]\n'
            f'env = {{ UNIFI_{upper}_HOST = "192.0.2.11" }}\n'
            'note = """\n# string content\n[mcp_servers.fake]\n"""\n'
        )
        lexical_cases = {
            "multiline basic": 'developer_instructions = """\nSample:\n'
            f'[mcp_servers.{name}]\ncommand = "old"\n'
            f'# unifi-plugin-setup: {name} example inside a string\n"""\n',
            "multiline literal": "developer_instructions = '''\nSample:\n"
            f"[[mcp_servers.{name}.example]]\ncommand = \"old\"\n'''\n",
            "arrays and comments": 'custom = [\n"""\n[mcp_servers.fake]\n""", # """ ignored\n'
            "['''\n[[mcp_servers.fake]]\n'''],\n]\n",
            "array tables": '[[custom]]\nlabel = "a"\n[[custom]]\nlabel = "b"\n',
            "escaped delimiters": 'developer_instructions = """\n'
            + r'\""" still inside the string'
            + '\n[mcp_servers.fake]\n"""\n',
            "closing quote runs": 'developer_instructions = """two trailing quotes"""""\n',
            "unicode line separators": 'developer_instructions = "first\u2028second"\n',
            "unicode keys": '[profiles."\\U0001F600"]\nmodel = "fixture"\n',
        }
        for label, prefix in lexical_cases.items():
            source = prefix + server_text
            if label == "unicode keys":
                source = source.replace(f'"{name}"', '"' + name[:-1] + f'\\U{ord(name[-1]):08X}"')
            expected = tomllib.loads(source)
            del expected["mcp_servers"][name]
            for eol in ("\n", "\r\n"):
                start(source.replace("\n", eol))
                result = run(refresh)
                self.check(result.returncode == 0, "conversion handles " + label)
                document = tomllib.loads(config.read_text(encoding="utf-8"))
                self.check(without_entry(document) == expected, "conversion keeps all TOML values for " + label)
                self.check(b"dropped the comments" not in result.stdout, "lexical layout needs no rewrite " + label)
                self.check(
                    config.read_bytes().startswith(prefix.replace("\n", eol).encode("utf-8")),
                    "conversion preserves unrelated TOML text for " + label,
                )

        # A scanner failure falls back to Codex's own removal in a private copy.
        scanner_injection = workspace / "scanner-injection"
        scanner_injection.mkdir()
        (scanner_injection / "sitecustomize.py").write_text(
            "import sys\n"
            "def boundary(frame, event, arg):\n"
            " if event == 'call' and frame.f_code.co_name == 'table_path':\n"
            "  raise ValueError('FAKE scanner failure')\n"
            "sys.setprofile(boundary)\n",
            encoding="utf-8",
        )
        start(source)
        result = run(refresh, PYTHONPATH=str(scanner_injection))
        document = tomllib.loads(config.read_text(encoding="utf-8"))
        self.check(
            result.returncode == 0 and b"dropped the comments" in result.stdout,
            "scanner exceptions use the validated Codex removal fallback",
        )
        self.check(without_entry(document) == expected, "scanner fallback keeps every other setting")

        # A layout setup cannot edit in place is rewritten by Codex, with a notice.
        start(
            f'# kept\n[mcp_servers]\nunrelated.command = "keep"\n"{name}".command = "old"\n'
            f'"{name}".env.UNIFI_{upper}_HOST = "192.0.2.12"\n'
        )
        result = run(refresh)
        document = tomllib.loads(config.read_text(encoding="utf-8"))
        self.check(result.returncode == 0 and b"dropped the comments" in result.stdout, "rewrite is announced")
        self.check(
            document["mcp_servers"] == {"unrelated": {"command": "keep"}}
            and setup.read_settings(path) == {f"UNIFI_{upper}_HOST": "192.0.2.12"},
            "dotted layout is converted through Codex",
        )

        # A value the settings file cannot hold refuses, leaving everything as it was.
        start(f'[mcp_servers."{name}"]\ncommand = "uvx"\nenv = {{ UNIFI_{upper}_HOST = "two\\nlines" }}\n')
        before = config.read_bytes()
        result = run(refresh)
        self.check(
            result.returncode != 0 and config.read_bytes() == before and not path.exists() and not backups(),
            "an unrepresentable value refuses without changes",
        )

        # Settings already saved are never overwritten by a differing entry.
        start(f'[mcp_servers."{name}"]\ncommand = "uvx"\nenv = {{ UNIFI_{upper}_HOST = "192.0.2.13" }}\n')
        before = config.read_bytes()
        path.write_text(setup.settings_text({f"UNIFI_{upper}_HOST": "192.0.2.14"}, name), encoding="utf-8")
        saved = path.read_bytes()
        result = run(refresh)
        self.check(
            result.returncode != 0 and config.read_bytes() == before and path.read_bytes() == saved,
            "differing file and entry refuse without changes",
        )
        # Matching settings (a rerun after an interrupted conversion) finish the conversion.
        path.write_text(setup.settings_text({f"UNIFI_{upper}_HOST": "192.0.2.13"}, name), encoding="utf-8")
        result = run(refresh)
        self.check(
            result.returncode == 0 and not tomllib.loads(config.read_text(encoding="utf-8")).get("mcp_servers"),
            "a matching rerun finishes the conversion",
        )

        # Ordinary setup converts too, applying the patch on top of the entry's settings.
        start(f'model = "fixture"\n[mcp_servers."{name}"]\ncommand = "uvx"\nenv = {{ UNIFI_{upper}_HOST = "a" }}\n')
        result = subprocess.run(
            command,
            input=json.dumps({f"UNIFI_{upper}_SITE": "fixture-site"}).encode(),
            cwd=workspace,
            env=environment,
            capture_output=True,
            timeout=30,
        )
        self.check(
            result.returncode == 0
            and setup.read_settings(path) == {f"UNIFI_{upper}_HOST": "a", f"UNIFI_{upper}_SITE": "fixture-site"}
            and tomllib.loads(config.read_text(encoding="utf-8")) == {"model": "fixture"},
            "ordinary setup converts a shadowing entry and applies the patch",
        )
        # Without an entry or a file there is nothing to convert.
        path.unlink()
        config.write_text('model = "fixture"\n', encoding="utf-8")
        result = run(refresh)
        self.check(result.returncode != 0 and not path.exists(), "refresh without saved settings refuses")
        config.unlink()
        for backup in backups():
            backup.unlink()

    def openclaw_conversion_scenario(self, workspace, environment, command, cached, path, product, setup):
        """Setup before plugin 1.0.0 saved an openclaw.json entry replacing the bundled server; one refresh moves it."""
        name = f"unifi-{product}"
        upper = product.upper()
        config = workspace / "openclaw/openclaw.json"
        refresh = command[:-1] + (["-Refresh"] if self.powershell else ["--refresh"])
        prerequisite = [
            *(
                [self.powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
                if self.powershell
                else [self.shell]
            ),
            str(cached / ("check-prereqs.ps1" if self.powershell else "check-prereqs.sh")),
            *(["-Target", "openclaw"] if self.powershell else ["--target", "openclaw"]),
        ]
        secret = 'FAKE-only "quoted" $dollar \\ tab\there Ω'
        pin = json.loads((cached.parent / ".mcp.codex.json").read_text(encoding="utf-8"))["mcpServers"][name]["args"][
            -1
        ]

        def run(argv, **extra):
            return subprocess.run(argv, cwd=workspace, env=dict(environment, **extra), capture_output=True, timeout=30)

        def backups():
            return sorted(config.parent.glob("openclaw.json.bak-*"))

        def start(document):
            path.unlink(missing_ok=True)
            for backup in backups():
                backup.unlink()
            config.write_text(json.dumps(document), encoding="utf-8")

        def private(file):
            return os.name == "nt" or file.stat().st_mode & 0o777 == 0o600

        moved = {f"UNIFI_{upper}_HOST": "192.0.2.10", f"UNIFI_{upper}_PASSWORD": secret, "UNIFI_POLICY_CREATE": "false"}
        unrelated = {"command": "keep", "env": {"KEEP": "yes"}}
        entry = {
            "command": "uvx",
            "args": ["--python-preference", "system", f"{name}-mcp==0.0.1"],
            "env": dict(moved, KEEP="old"),
            "enabled": True,
        }
        document = {"custom": {"keep": [True]}, "mcp": {"servers": {"unrelated": unrelated, name: entry}}}
        start(document)
        source = config.read_bytes()
        checked = run(prerequisite)
        self.check(
            checked.returncode == 0
            and b"openclaw.json has an MCP entry" in checked.stdout
            and (b"-Target openclaw -Refresh" if self.powershell else b"--target openclaw --refresh") in checked.stdout,
            "prerequisites name the replacing OpenClaw entry and its one-time refresh",
        )
        self.check(config.read_bytes() == source and not path.exists(), "the prerequisite check changes nothing")
        argv_path = workspace / "argv.jsonl"
        argv_path.unlink(missing_ok=True)
        result = run(refresh)
        self.check(result.returncode == 0, "refresh converts the OpenClaw entry without input")
        self.check(setup.read_settings(path) == moved, "conversion moves exactly the entry's UNIFI_ settings")
        self.check(private(path), "converted settings file is private (600)")
        calls = [json.loads(line) for line in argv_path.read_text(encoding="utf-8").splitlines()]
        self.check(
            [call for call in calls if call[0] == "openclaw"] == [["openclaw", "mcp", "unset", name]],
            "the entry is removed with openclaw mcp unset only",
        )
        remaining = json.loads(config.read_text(encoding="utf-8"))
        self.check(
            remaining == {"custom": {"keep": [True]}, "mcp": {"servers": {"unrelated": unrelated}}},
            "conversion keeps every other OpenClaw setting",
        )
        [backup] = backups()
        self.check(backup.read_bytes() == source and private(backup), "private exact backup")
        self.check(
            b"Not moved" in result.stdout and b"KEEP" in result.stdout and b"enabled" in result.stdout,
            "conversion names what it did not move",
        )
        self.check(pin.encode() in result.stdout, "conversion names the bundled server's pin")
        self.check(
            b"at its next agent turn" in result.stdout and b"gateway restart" not in result.stdout,
            "conversion says the running gateway loads it at the next agent turn",
        )
        self.check(secret.encode() not in result.stdout + result.stderr, "conversion output omits values")
        self.check(secret not in argv_path.read_text(encoding="utf-8"), "conversion argv omits values")
        checked = run(prerequisite)
        self.check(checked.returncode == 0 and b"has an MCP entry" not in checked.stdout, "notice goes quiet")
        again = run(refresh)
        self.check(
            again.returncode == 0 and b"Nothing to convert" in again.stdout and len(backups()) == 1,
            "a second refresh changes nothing",
        )

        # Settings already saved are never overwritten by a differing entry.
        start(document)
        before = config.read_bytes()
        path.write_text(setup.settings_text({f"UNIFI_{upper}_HOST": "192.0.2.14"}, name), encoding="utf-8")
        saved = path.read_bytes()
        result = run(refresh)
        self.check(
            result.returncode != 0 and config.read_bytes() == before and path.read_bytes() == saved and not backups(),
            "differing file and entry refuse without changes",
        )

        # A failing or overreaching OpenClaw CLI leaves the saved settings and a backup; a rerun finishes.
        for failure in ("unset", "overreach"):
            start(document)
            result = run(refresh, FIXTURE_FAIL=failure)
            self.check(
                result.returncode != 0
                and setup.read_settings(path) == moved
                and len(backups()) == 1
                and backups()[0].read_bytes() == before,
                f"a {failure} failure keeps the settings and the backup",
            )
            self.check(
                b"openclaw mcp unset " + name.encode() in result.stderr
                and (workspace / "client-output-marker").read_bytes() not in result.stdout + result.stderr,
                f"a {failure} failure names the manual removal and hides client output",
            )
            self.check(not list(config.parent.glob("*.setup-lock")), f"a {failure} failure leaves no lock")
            if failure == "unset":
                self.check(config.read_bytes() == before, "a failed unset leaves openclaw.json unchanged")
                result = run(refresh)
                self.check(
                    result.returncode == 0 and name not in json.loads(config.read_text())["mcp"]["servers"],
                    "a matching rerun finishes the conversion",
                )

        # Ordinary setup converts too, applying the patch on top of the entry's settings.
        start({"mcp": {"servers": {name: {"command": "uvx", "env": {f"UNIFI_{upper}_HOST": "a"}}}}})
        result = subprocess.run(
            command,
            input=json.dumps({f"UNIFI_{upper}_SITE": "fixture-site"}).encode(),
            cwd=workspace,
            env=environment,
            capture_output=True,
            timeout=30,
        )
        self.check(
            result.returncode == 0
            and setup.read_settings(path) == {f"UNIFI_{upper}_HOST": "a", f"UNIFI_{upper}_SITE": "fixture-site"}
            and json.loads(config.read_text(encoding="utf-8")) == {"mcp": {"servers": {}}},
            "ordinary setup converts the OpenClaw entry and applies the patch",
        )
        # Without an entry or a file there is nothing to convert.
        path.unlink()
        start({"mcp": {"servers": {"unrelated": unrelated}}})
        result = run(refresh)
        self.check(result.returncode != 0 and not path.exists() and not backups(), "refresh without settings refuses")
        config.unlink()
        for backup in backups():
            backup.unlink()

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
        # Codex and OpenClaw settings live in the per-user file the bundled server reads.
        setup = setup_module(scripts)
        keep = "UNIFI_FIXTURE_KEEP"
        saved = {keep: "old", base: "FAKE-old"}
        path = workspace / ".config" / "unifi-mcp" / f"{product}.env"
        (workspace / target).mkdir()
        path.parent.mkdir(parents=True)

        def seed():
            path.write_text(setup.settings_text(saved, f"unifi-{product}"), encoding="utf-8")
            path.chmod(0o600)

        def load():
            return setup.read_settings(path)

        def get_env(data):
            return data

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
            lines = argv_path.read_text(encoding="utf-8").splitlines() if argv_path.exists() else []
            managed = [call for call in map(json.loads, lines) if call[0] == "uv"]
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
        invoke({base: sample_value})
        data = load()
        self.check(get_env(data)[base] == sample_value, "special characters round-trip")
        self.check(get_env(data)[keep] == "old", "unrelated environment preserved")
        self.check(os.name == "nt" or path.stat().st_mode & 0o777 == 0o600, "settings file is private (600)")
        self.check(not list(path.parent.glob(".*unifi-setup-*")), "no staged settings file remains")
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
        # A deprecated UNIFI_AUTO_CONFIRM stays in the registration but is always named, never valued.
        for value, effect in (("yes", b"turns on bypass"), ("garbage-marker", b"no effect")):
            result = invoke({"UNIFI_AUTO_CONFIRM": value})
            self.check(get_env(load())["UNIFI_AUTO_CONFIRM"] == value, "auto-confirm is kept, not dropped")
            self.check(
                b"UNIFI_AUTO_CONFIRM is deprecated" in result.stdout and effect in result.stdout,
                f"setup names the deprecated auto-confirm and what it does ({value})",
            )
            self.check(
                (effect == b"no effect" or b"UNIFI_TOOL_PERMISSION_MODE=bypass" in result.stdout)
                and b"UNIFI_AUTO_CONFIRM=" not in result.stdout + result.stderr
                and (value != "garbage-marker" or value.encode() not in result.stdout + result.stderr),
                "setup says what to set instead and omits the auto-confirm value",
            )
        quiet = invoke({base: sample_value})
        self.check(
            b"UNIFI_AUTO_CONFIRM" in quiet.stdout, "an unrelated setup still names a carried-forward auto-confirm"
        )
        result = invoke({"UNIFI_AUTO_CONFIRM": None})
        self.check("UNIFI_AUTO_CONFIRM" not in get_env(load()), "null deletion removes auto-confirm")
        self.check(b"UNIFI_AUTO_CONFIRM" not in result.stdout, "a removed auto-confirm is no longer named")
        # Installed Codex plugins include a version directory in their path; OpenClaw's do not, and both work.
        cached = workspace / "cache" / f"unifi-{product}" / "9.8.7" / "scripts"
        cached.mkdir(parents=True)
        for source in scripts.iterdir():
            if source.is_file():
                shutil.copy2(source, cached / source.name)
        for directory in (".codex-plugin", ".claude-plugin"):
            shutil.copytree(scripts.parent / directory, cached.parent / directory)
        shutil.copy2(scripts.parent / ".mcp.codex.json", cached.parent / ".mcp.codex.json")
        suffix = "set-env.ps1" if self.powershell else "set-env.sh"
        command[command.index(str(scripts / suffix))] = str(cached / suffix)
        first = invoke({f"UNIFI_{product.upper()}_HOST": "192.0.2.99"})
        self.check(
            get_env(load())[f"UNIFI_{product.upper()}_HOST"] == "192.0.2.99",
            "versioned plugin cache uses the product's settings file",
        )
        if target == "openclaw":
            self.check(
                b"new OpenClaw session" in first.stdout
                and b"openclaw gateway restart" in first.stdout
                and b"already open keeps the unconfigured server" in first.stdout
                and b"next agent turn" not in first.stdout,
                "ordinary OpenClaw setup says an open session keeps the unconfigured server",
            )
        if target == "codex":
            self.check(not (workspace / "codex/config.toml").exists(), "Codex setup writes no config.toml entry")
            self.codex_conversion_scenario(workspace, environment, command, cached, path, product, setup)
        else:
            self.check(
                not (workspace / "openclaw/openclaw.json").exists(), "OpenClaw setup writes no openclaw.json entry"
            )
            self.openclaw_conversion_scenario(workspace, environment, command, cached, path, product, setup)
        seed()
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
        try:
            main()
        except Exception as error:
            report_failure(error)
            sys.exit(1)
