#!/usr/bin/env python3
"""Private staging and atomic publication for the three plugin setup wrappers.

Values enter on stdin only. Never execute credential providers or start servers.
Client output and exception text are deliberately excluded from diagnostics.
"""

import argparse
import datetime
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


class SetupError(Exception):
    """A fixed, credential-free recovery message."""


def refuse(message):
    raise SetupError(message)


def json_object(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                refuse("Duplicate JSON keys are unsupported; repair the configuration and rerun.")
            result[key] = value
        return result

    def invalid_constant(_value):
        refuse("Non-finite JSON values are unsupported; repair the configuration and rerun.")

    data = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    if not isinstance(data, dict):
        refuse("Configuration must be a JSON object; repair it and rerun.")
    return data


def env_map(value):
    if not isinstance(value, dict) or any(not isinstance(v, str) for v in value.values()):
        refuse("The existing env must be an object of strings; repair it and rerun.")
    return dict(value)


def secret_base(key):
    return re.fullmatch(r"(UNIFI_(?:(?:NETWORK|PROTECT|ACCESS)_)?(?:PASSWORD|API_KEY))(.*)", key)


def validate_key(key):
    if not re.fullmatch(r"UNIFI_[A-Z][A-Z0-9_]*", key):
        refuse("Use uppercase UNIFI_ environment variable names; no settings were changed.")
    match = secret_base(key)
    if match and match[2] not in ("", "_FILE", "_COMMAND"):
        refuse("Unknown credential provider. Use the plain, _FILE or _COMMAND spelling.")


def validate_provider(key, value):
    if not value or not secret_base(key):
        return
    if key.endswith("_FILE"):
        path = Path(value)
        if not path.is_absolute():
            refuse("Credential file providers need an absolute path; no settings were changed.")
        if not path.is_file() or not os.access(path, os.R_OK) or path.stat().st_size == 0:
            refuse("Credential provider file is missing, unreadable or empty; repair it and rerun.")
    if key.endswith("_COMMAND"):
        argv = shlex.split(value)
        if not argv or (not Path(argv[0]).is_absolute() and ("/" in argv[0] or "\\" in argv[0])):
            refuse("Credential command providers need an absolute executable or a bare command name.")
        if not shutil.which(argv[0]):
            refuse("Credential provider executable is unavailable; install it or correct PATH and rerun.")


def merge_env(existing, patch, product):
    merged = env_map(existing)
    for key, value in patch.items():
        validate_key(key)
        if value is not None and (not isinstance(value, str) or "\0" in value):
            refuse("Environment patch values must be strings or null deletions, without NUL bytes.")
        if value is not None:
            validate_provider(key, value)
    bases = {secret_base(key)[1] for key in patch if secret_base(key)}
    for base in bases:
        selected = [k for k in (base, base + "_FILE", base + "_COMMAND") if patch.get(k)]
        if len(selected) > 1:
            refuse("Select exactly one spelling of each credential at each precedence level.")
        if selected:
            for key in (base, base + "_FILE", base + "_COMMAND"):
                merged.pop(key, None)
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    effective = dict(os.environ)
    effective.update(merged)
    # Match resolve_env: only the first non-empty level is resolved.
    for credential in ("PASSWORD", "API_KEY"):
        for base in (f"UNIFI_{product}_{credential}", f"UNIFI_{credential}"):
            selected = [key for key in (base, base + "_FILE", base + "_COMMAND") if effective.get(key)]
            if len(selected) > 1:
                refuse("Credential providers conflict in the effective environment; keep one spelling per level.")
            if selected:
                validate_provider(selected[0], effective[selected[0]])
                break
    return merged


def client(command, environment):
    executable = shutil.which(command[0], path=environment.get("PATH"))
    if executable is None:
        refuse("The selected client CLI is missing from PATH; install it and rerun.")
    # Windows npm installs expose .cmd launchers; CreateProcess does not apply
    # PATHEXT when given the bare client name. Only fixed, non-secret args follow.
    command = [executable, *command[1:]]
    completed = subprocess.run(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if completed.returncode:
        refuse(
            "Client registration or validation failed. Existing configuration is unchanged; "
            "check client compatibility and rerun."
        )
    return completed.stdout


def toml_value(value):
    # Only the server entry is serialized; client tooling preserves other tables.
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(k) + " = " + toml_value(v) for k, v in value.items()) + " }"
    refuse("Unsupported existing server value; use the client configuration editor and rerun.")


def read_config(path, target):
    raw = path.read_bytes() if path.exists() else None
    if target == "codex":
        import tomllib

        data = tomllib.loads(raw.decode("utf-8")) if raw is not None else {}
        servers = data.get("mcp_servers", {})
    else:
        data = json_object(raw.decode("utf-8-sig")) if raw is not None else {}
        if target == "claude":
            env_map(data.get("env", {}))
            return raw, data, {}
        if not isinstance(data.get("mcp", {}), dict):
            refuse("The mcp setting must be an object; repair it and rerun.")
        servers = data.get("mcp", {}).get("servers", {})
    if not isinstance(servers, dict):
        refuse("The MCP registry must be an object; repair it and rerun.")
    return raw, data, servers


def package_pin(root, name):
    for filename in (root / ".claude-plugin/plugin.json", root / ".mcp.json"):
        if filename.exists():
            match = re.search(
                r"unifi-(?:network|protect|access)-mcp==[0-9][A-Za-z0-9.+-]*", filename.read_text(encoding="utf-8")
            )
            if match:
                return match[0]
    return name + "-mcp@latest"


def main():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            refuse("Unsupported setup arguments; choose claude, codex or openclaw.")

    parser = SafeParser(description=__doc__)
    parser.add_argument("--target", choices=("claude", "codex", "openclaw"), default="claude")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--pairs", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        refuse("No usable setup interpreter; install uv (which supplies Python) and rerun.")
    root = Path(__file__).resolve().parent.parent
    name = root.name if root.name in ("unifi-network", "unifi-protect", "unifi-access") else root.parent.name
    if name not in ("unifi-network", "unifi-protect", "unifi-access"):
        refuse("Cannot identify the plugin; rerun from a complete plugin installation.")
    product = name.removeprefix("unifi-").upper()
    target = args.target
    if not shutil.which("uvx"):
        refuse("uvx is required; install uv from https://astral.sh/uv/install.sh and rerun.")
    if target != "claude" and not shutil.which(target):
        refuse("The selected client CLI is missing from PATH; install it and rerun.")
    if target == "claude":
        destination = Path.cwd() / ".claude/settings.local.json"
    elif target == "codex":
        destination = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    else:
        state = Path(os.environ.get("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw")))
        destination = Path(os.environ.get("OPENCLAW_CONFIG_PATH", str(state / "openclaw.json")))
    destination = destination.expanduser().absolute()
    if destination.is_symlink():
        refuse("Configuration symlinks are unsupported; use the client editor for this installation.")
    original, data, servers = read_config(destination, target)
    prior = servers.get(name, {})
    if not isinstance(prior, dict):
        refuse("The existing MCP server must be an object; repair it and rerun.")
    previous_env = data.get("env", {}) if target == "claude" else prior.get("env", {})
    env_map(previous_env)
    if args.check:
        merge_env(previous_env, {}, product)
        print("Prerequisites passed: uvx, setup runtime, client and configuration shape checked.")
        return
    raw_input = sys.stdin.buffer.read().decode("utf-8-sig")
    if args.pairs:
        patch = {}
        for pair in raw_input.rstrip("\0").split("\0"):
            key, sep, value = pair.partition("=")
            if not sep:
                refuse("Expected non-secret KEY=VALUE arguments or --input-json.")
            if re.search(r"(?:PASSWORD|API_KEY|TOKEN|SECRET)", key) and not key.endswith(("_FILE", "_COMMAND")):
                refuse(
                    "Raw credentials cannot be command arguments. "
                    "Pipe a JSON patch with --input-json or use a provider reference."
                )
            if key in patch:
                refuse("Duplicate environment patch keys are unsupported.")
            patch[key] = value
    else:
        patch = json_object(raw_input)
    if not patch:
        refuse("Supply at least one environment setting or null deletion.")
    merged = merge_env(previous_env, patch, product)
    if args.dry_run:
        print("Validation passed; dry run made no changes. Values are omitted.")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Cooperating setup calls serialize; a killed process leaves a harmless lock.
    lock = destination.with_name(destination.name + ".setup-lock")
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        refuse("Setup is locked. If no setup is running, remove the adjacent .setup-lock directory and rerun.")
    try:
        if (destination.read_bytes() if destination.exists() else None) != original:
            refuse("Configuration changed during setup; rerun against the latest settings.")
        with tempfile.TemporaryDirectory(prefix=".unifi-setup-", dir=destination.parent) as temporary:
            stage = Path(temporary)
            staged = stage / destination.name
            staged.write_bytes(original or (b"" if target == "codex" else b"{}"))
            staged.chmod(0o600)
            environment = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_")}
            environment.update(
                HOME=str(stage),
                USERPROFILE=str(stage),
                CODEX_HOME=str(stage),
                CLAUDE_CONFIG_DIR=str(stage / ".claude"),
                OPENCLAW_STATE_DIR=str(stage),
                OPENCLAW_CONFIG_PATH=str(staged),
            )
            if target == "claude":
                data["env"] = merged
                staged.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                read_config(staged, target)
            elif target == "codex":
                # Exercise the supported operation only in a private CODEX_HOME.
                client(
                    [
                        "codex",
                        "mcp",
                        "add",
                        name,
                        "--",
                        "uvx",
                        "--python-preference",
                        "system",
                        package_pin(root, name),
                    ],
                    environment,
                )
                client(["codex", "mcp", "remove", name], environment)
                entry = dict(prior)
                for key in ("url", "bearer_token_env_var", "http_headers", "env_http_headers"):
                    entry.pop(key, None)
                entry.update(command="uvx", args=["--python-preference", "system", package_pin(root, name)], env=merged)
                with staged.open("a", encoding="utf-8") as handle:
                    handle.write("\n[mcp_servers." + json.dumps(name) + "]\n")
                    for key, value in entry.items():
                        handle.write(json.dumps(key) + " = " + toml_value(value) + "\n")
                _, final_data, final_servers = read_config(staged, target)
                if final_servers.get(name) != entry:
                    refuse("Staged registry validation failed; existing configuration is unchanged.")
                expected_data = dict(data)
                expected_data["mcp_servers"] = dict(servers, **{name: entry})
                if final_data != expected_data:
                    refuse("The client changed unrelated settings; existing configuration is unchanged.")
                checked = json_object(client(["codex", "mcp", "get", name, "--json"], environment).decode("utf-8"))
                if checked.get("transport", {}).get("env") != merged:
                    refuse("The client did not retain the requested environment; existing configuration is unchanged.")
            else:
                entry = dict(prior)
                for key in ("url", "headers", "transport"):
                    entry.pop(key, None)
                entry.update(command="uvx", args=["--python-preference", "system", package_pin(root, name)])
                entry["env"] = {}
                # No supplied setting, even a provider reference, enters CLI argv.
                client(
                    ["openclaw", "mcp", "set", name, json.dumps({"command": "uvx", "args": entry["args"]})], environment
                )
                read_config(staged, target)
                entry["env"] = merged
                data.setdefault("mcp", {}).setdefault("servers", {})[name] = entry
                staged.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                read_config(staged, target)
                client(["openclaw", "config", "validate", "--json"], environment)
            staged.chmod(0o600)
            # Windows FlushFileBuffers (used by fsync) requires write access.
            # Reopen without truncating the complete, validated staged file.
            with staged.open("r+b") as handle:
                os.fsync(handle.fileno())
            if (destination.read_bytes() if destination.exists() else None) != original:
                refuse("Configuration changed during setup; rerun against the latest settings.")
            os.replace(staged, destination)
    finally:
        lock.rmdir()
    print("Configuration saved atomically. Restart the selected client to load it. Values are omitted.")


if __name__ == "__main__":
    # A signal before replace leaves the original intact; after replace it leaves
    # the complete validated replacement. Never print exception data or input.
    def interrupted(_signum, _frame):
        raise SetupError("Setup interrupted; the configuration remains complete. Rerun setup when ready.")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        main()
    except SetupError as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print(
            "ERROR: Setup could not validate or save configuration. Existing configuration is unchanged; "
            "check syntax, providers, dependencies and permissions, then rerun.",
            file=sys.stderr,
        )
        sys.exit(1)
