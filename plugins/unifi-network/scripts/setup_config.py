#!/usr/bin/env python3
"""Private staging and atomic publication for the three plugin setup wrappers.

Values enter on stdin only. Never execute credential providers or start servers.
Client output and exception text are deliberately excluded from diagnostics.
Claude Code options are saved through its own CLI; Codex and OpenClaw registries
are staged privately and replaced atomically.
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


def merge_env(existing, patch, product, inherited=None):
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
    effective = dict(os.environ if inherited is None else inherited)
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


def client(command, environment, data=None):
    executable = shutil.which(command[0], path=environment.get("PATH"))
    if executable is None:
        refuse("The selected client CLI is missing from PATH; install it and rerun.")
    # Windows npm installs expose .cmd launchers; CreateProcess does not apply
    # PATHEXT when given the bare client name. Only fixed, non-secret args follow;
    # values travel on stdin.
    command = [executable, *command[1:]]
    completed = subprocess.run(
        command,
        env=environment,
        input=data if data is not None else b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
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
        if not isinstance(data.get("mcp", {}), dict):
            refuse("The mcp setting must be an object; repair it and rerun.")
        servers = data.get("mcp", {}).get("servers", {})
    if not isinstance(servers, dict):
        refuse("The MCP registry must be an object; repair it and rerun.")
    return raw, data, servers


def package_pin(root, name, *, codex=False):
    files = (root / ".claude-plugin/plugin.json", root / ".mcp.json")
    if codex:
        files = (root / ".mcp.codex.json", *files)
    for filename in files:
        if filename.exists():
            match = re.search(
                r"unifi-(?:network|protect|access)-mcp==[0-9][A-Za-z0-9.+-]*", filename.read_text(encoding="utf-8")
            )
            if match:
                return match[0]
    return name + "-mcp@latest"


# Claude Code stores plugin options itself (user settings, sensitive values in the
# system keychain); the shipped .mcp.json maps each option onto one variable.
# A configured sensitive option whose value Claude never reveals. NUL cannot occur
# in a real value: patches refuse it.
KEYCHAIN = "\0claude-keychain\0"
TRUTHY = ("true", "1", "yes", "on")
FALSY = ("false", "0", "no", "off")


def claude_options(root):
    """Return {variable: option} and the option schema from the installed plugin."""
    try:
        schema = json_object((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8")).get("userConfig")
        servers = json_object((root / ".mcp.json").read_text(encoding="utf-8")).get("mcpServers")
    except (OSError, ValueError):
        schema = servers = None
    if not isinstance(schema, dict) or not isinstance(servers, dict) or len(servers) != 1:
        refuse("The installed plugin's Claude Code options are missing or inconsistent; reinstall the plugin.")
    mapping = {}
    for variable, template in (next(iter(servers.values())).get("env") or {}).items():
        match = re.fullmatch(r"\$\{user_config\.([A-Za-z_][A-Za-z0-9_]*)\}", str(template))
        if not match or not isinstance(schema.get(match[1]), dict):
            refuse("The installed plugin's Claude Code options are missing or inconsistent; reinstall the plugin.")
        mapping[variable] = match[1]
    return mapping, schema


def option_default(entry):
    value = entry.get("default")
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def option_text(entry, value):
    """Normalize a variable value to the option's single-line string form."""
    if "\n" in value or "\r" in value:
        refuse("Claude Code options hold single-line values; correct the value and rerun.")
    if value == "":
        return option_default(entry)
    if entry.get("type") == "boolean":
        if value.strip().lower() not in TRUTHY + FALSY:
            refuse("A Claude Code on/off option accepts true or false; no settings were changed.")
        return "true" if value.strip().lower() in TRUTHY else "false"
    if entry.get("type") == "number":
        if not re.fullmatch(r"[0-9]{1,9}", value.strip()):
            refuse("A Claude Code number option accepts digits only; no settings were changed.")
        number = int(value)
        if number < entry.get("min", number) or number > entry.get("max", number):
            refuse("A Claude Code number option is out of range; no settings were changed.")
        return str(number)
    if entry.get("options") and value not in entry["options"]:
        refuse("A Claude Code option accepts only its listed choices; no settings were changed.")
    return value


def claude_plugin_id(root, environment):
    try:
        listed = json.loads(client(["claude", "plugin", "list", "--json"], environment).decode("utf-8"))
    except ValueError:
        listed = None
    for entry in listed if isinstance(listed, list) else []:
        path = entry.get("installPath") if isinstance(entry, dict) else None
        if isinstance(path, str) and isinstance(entry.get("id"), str) and Path(path).resolve() == root.resolve():
            return entry["id"]
    refuse(
        "Claude Code does not list this plugin installation. Install the plugin with claude plugin install "
        "and run setup from the installed copy."
    )


def claude_saved(plugin_id, environment, mapping, schema):
    """Read the saved options as variables; keychain values stay unknown."""
    try:
        state = json_object(client(["claude", "plugin", "configure", plugin_id, "--json"], environment).decode("utf-8"))
    except ValueError:
        state = {}
    inputs, configured = state.get("inputs"), state.get("configured")
    if not isinstance(inputs, dict) or not isinstance(configured, list):
        refuse("Claude Code returned no readable plugin options; update Claude Code and rerun.")
    saved = {}
    for variable, option in mapping.items():
        entry = schema[option]
        if entry.get("sensitive"):
            if option in configured:
                saved[variable] = KEYCHAIN
            continue
        value = inputs.get(option, "")
        if not isinstance(value, str):
            refuse("Claude Code returned no readable plugin options; update Claude Code and rerun.")
        if value := option_text(entry, value):
            saved[variable] = value
    return saved


def claude_values(variables, mapping, schema):
    """Option strings Claude would hold for these variables (keychain values stay opaque)."""
    values = {}
    for variable, option in mapping.items():
        value = variables.get(variable, "")
        values[option] = value if value == KEYCHAIN else option_text(schema[option], value)
    return values


def legacy_settings(product):
    """Project settings written by earlier plugin versions, split by ownership."""
    path = Path.cwd() / ".claude/settings.local.json"
    if not path.is_file():
        return path, None, {}, {}
    try:
        if path.is_symlink():
            raise ValueError
        data = json_object(path.read_bytes().decode("utf-8-sig"))
        env = env_map(data.get("env", {}))
    except (SetupError, OSError, ValueError):
        return path, False, {}, {}
    others = tuple(f"UNIFI_{p}_" for p in ("NETWORK", "PROTECT", "ACCESS") if p != product)
    others += tuple(f"UNIFI_POLICY_{p}_" for p in ("NETWORK", "PROTECT", "ACCESS") if p != product)
    owned = {k: v for k, v in env.items() if k.startswith((f"UNIFI_{product}_", f"UNIFI_POLICY_{product}_"))}
    shared = {k: v for k, v in env.items() if k.startswith("UNIFI_") and k not in owned and not k.startswith(others)}
    return path, data, owned, shared


def shared_name(variable, product):
    for prefix in (f"UNIFI_{product}_", f"UNIFI_POLICY_{product}_"):
        if variable.startswith(prefix):
            return prefix.replace(f"{product}_", "") + variable[len(prefix) :]
    return variable


def legacy_patch(owned, shared, mapping, product):
    """Translate legacy project variables into this plugin's option variables."""
    legacy = dict(shared, **owned)
    patch = {}
    for credential in ("PASSWORD", "API_KEY"):
        product_base = f"UNIFI_{product}_{credential}"
        for base in (product_base, f"UNIFI_{credential}"):
            spellings = [base + suffix for suffix in ("", "_FILE", "_COMMAND")]
            if any(legacy.get(key) for key in spellings):
                for key in spellings:
                    if legacy.get(key):
                        patch[product_base + key[len(base) :]] = legacy[key]
                break
    for variable in mapping:
        if secret_base(variable) or variable in patch:
            continue
        value = legacy.get(variable) or legacy.get(shared_name(variable, product))
        if value:
            patch[variable] = value
    return patch


def publish_project_settings(handle, destination):
    """Atomically publish without disabling Windows delete-on-close cleanup."""
    if os.name != "nt":
        os.replace(handle.name, destination)
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes

    # Renaming a delete-on-close file would delete the destination on close.
    # Instead replace the destination's hard link while keeping the temporary
    # link owned by the handle. Termination removes only that temporary link.
    # FILE_LINK_INFORMATION / NtSetInformationFile, FileLinkInformation (11).
    filename = str(destination.absolute())
    filename = "\\??\\UNC\\" + filename[2:] if filename.startswith("\\\\") else "\\??\\" + filename
    encoded = filename.encode("utf-16-le")

    class LinkInformation(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", ctypes.c_ubyte),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.ULONG),
            ("FileName", ctypes.c_ushort * (len(encoded) // 2)),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    info = LinkInformation(ReplaceIfExists=1, FileNameLength=len(encoded))
    ctypes.memmove(ctypes.addressof(info) + LinkInformation.FileName.offset, encoded, len(encoded))
    status = IoStatusBlock()
    set_information = ctypes.WinDLL("ntdll").NtSetInformationFile
    set_information.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG, ctypes.c_int]
    set_information.restype = wintypes.LONG
    result = set_information(
        msvcrt.get_osfhandle(handle.fileno()), ctypes.byref(status), ctypes.byref(info), ctypes.sizeof(info), 11
    )
    if result < 0:
        refuse(
            "Windows could not atomically replace project settings on this filesystem. "
            "Plugin options were saved; project settings are unchanged. Rerun migration on a filesystem "
            "supporting hard links, and check permissions and open files."
        )


def replace_project_settings(destination, original, remaining):
    # Keep settings in memory during Claude calls. The Windows temporary file
    # uses O_TEMPORARY: the OS deletes it even after taskkill /F, without finally.
    with tempfile.NamedTemporaryFile(prefix=".unifi-setup-", dir=destination.parent, delete=os.name == "nt") as handle:
        try:
            handle.write((json.dumps(remaining, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
            if destination.read_bytes() != original:
                refuse("Project settings changed during migration; the plugin options were saved, rerun to finish.")
            publish_project_settings(handle, destination)
        finally:
            if os.name != "nt":
                Path(handle.name).unlink(missing_ok=True)


def claude_main(args, root, name, product):
    mapping, schema = claude_options(root)
    environment = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_")}
    plugin_id = claude_plugin_id(root, environment)
    saved = claude_saved(plugin_id, environment, mapping, schema)
    # The server's env lists every option variable, so inherited values of those
    # names never reach it; only other inherited variables can.
    inherited = {k: v for k, v in os.environ.items() if k not in mapping}
    legacy_path, legacy_data, owned, shared = legacy_settings(product)
    notice = None
    if legacy_data is False:
        notice = "Notice: .claude/settings.local.json in this project could not be read to check for legacy settings."
    elif owned and not args.migrate:
        notice = (
            "Notice: .claude/settings.local.json in this project still holds settings that this plugin version "
            "no longer reads (" + ", ".join(sorted(owned)) + "). Move them into the plugin's options with "
            "set-env.sh --target claude --migrate (PowerShell: set-env.ps1 -Target claude -Migrate)."
        )
    if args.check:
        merge_env(saved, {}, product, inherited)
        if notice:
            print(notice)
        print("Prerequisites passed: uvx, setup runtime, Claude Code plugin options and configuration checked.")
        return
    if args.migrate:
        if legacy_data is False:
            refuse("Cannot read .claude/settings.local.json in this project; repair it and rerun the migration.")
        if not owned:
            refuse("No legacy settings for this plugin were found in .claude/settings.local.json; nothing to migrate.")
        patch = legacy_patch(owned, shared, mapping, product)
        if not patch:
            refuse("The legacy settings hold no value this plugin's Claude Code options can use; run setup instead.")
    else:
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
    for key in patch:
        validate_key(key)
    unsupported = sorted(key for key in patch if key not in mapping)
    if unsupported:
        refuse(
            "Claude Code has no plugin option for " + ", ".join(unsupported) + ". Claude Code supports the "
            "server-level create, update and delete gates, not per-category policy overrides; no settings were changed."
        )
    merged = merge_env(saved, patch, product, inherited)
    wanted = claude_values(merged, mapping, schema)
    before = claude_values(saved, mapping, schema)
    changes = {option: value for option, value in wanted.items() if value != KEYCHAIN and value != before[option]}
    if args.dry_run:
        print("Validation passed; dry run made no changes. Values are omitted.")
        return
    remaining = None
    if args.migrate:
        remaining = dict(legacy_data)
        remaining["env"] = {k: v for k, v in legacy_data["env"].items() if k not in owned}
        original = legacy_path.read_bytes()
    if claude_saved(plugin_id, environment, mapping, schema) != saved:
        refuse("The plugin's options changed during setup; rerun against the latest options.")
    if changes:
        client(
            ["claude", "plugin", "configure", plugin_id, "--values-stdin"],
            environment,
            json.dumps(changes, ensure_ascii=False).encode("utf-8"),
        )
        after = claude_values(claude_saved(plugin_id, environment, mapping, schema), mapping, schema)
        retained = all(
            (after[option] == KEYCHAIN) == bool(value) if schema[option].get("sensitive") else after[option] == value
            for option, value in changes.items()
        )
        if not retained:
            restore = {o: before[o] for o in changes if before[o] != KEYCHAIN and not schema[o].get("sensitive")}
            if restore:
                client(
                    ["claude", "plugin", "configure", plugin_id, "--values-stdin"],
                    environment,
                    json.dumps(restore, ensure_ascii=False).encode("utf-8"),
                )
            refuse("Claude Code did not retain the requested options; previous non-secret options were restored.")
    if remaining is not None:
        replace_project_settings(legacy_path, original, remaining)
    if args.migrate:
        print(
            "Migrated " + ", ".join(sorted(k for k in owned if k in patch)) + " into the plugin's Claude Code options "
            "and removed " + ", ".join(sorted(owned)) + " from .claude/settings.local.json. Values are omitted."
        )
        dropped = sorted(k for k in owned if k not in patch)
        if dropped:
            print("Not migrated (no Claude Code option): " + ", ".join(dropped) + ".")
        if shared:
            print(
                "Shared settings left in .claude/settings.local.json for other UniFi plugins: "
                + ", ".join(sorted(shared))
                + ". Remove them once every UniFi plugin is migrated."
            )
    elif notice:
        print(notice)
    print(
        "Claude Code plugin options saved for " + plugin_id + ". Start a new Claude Code session; if the server "
        "is not connected, run /mcp reconnect plugin:" + name + ":" + name + ". Values are omitted."
    )


def main():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            refuse("Unsupported setup arguments; choose claude, codex or openclaw.")

    parser = SafeParser(description=__doc__)
    parser.add_argument("--target", choices=("claude", "codex", "openclaw"), default="claude")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--pairs", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Re-pin Codex using the saved environment")
    parser.add_argument(
        "--migrate", action="store_true", help="Move legacy Claude project settings into plugin options"
    )
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        refuse("No usable setup interpreter; install uv (which supplies Python) and rerun.")
    root = Path(__file__).resolve().parent.parent
    name = root.name if root.name in ("unifi-network", "unifi-protect", "unifi-access") else root.parent.name
    if name not in ("unifi-network", "unifi-protect", "unifi-access"):
        refuse("Cannot identify the plugin; rerun from a complete plugin installation.")
    product = name.removeprefix("unifi-").upper()
    target = args.target
    if args.refresh and (target != "codex" or args.pairs or args.check):
        refuse("Refresh is only supported for an existing Codex registration, without environment arguments.")
    if args.migrate and (target != "claude" or args.pairs or args.check):
        refuse("Migration is only supported for Claude Code, without environment arguments.")
    pin = package_pin(root, name, codex=True) if target == "codex" else None
    plugin_version = None
    if target == "codex" and not args.check:
        manifest = root / ".codex-plugin/plugin.json"
        # Legacy installations can use the Claude manifest as their identity.
        if not manifest.is_file():
            manifest = root / ".claude-plugin/plugin.json"
        if manifest.is_file():
            plugin_version = json_object(manifest.read_text(encoding="utf-8")).get("version")
        if (
            not isinstance(plugin_version, str)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", plugin_version)
            or not re.fullmatch(re.escape(name) + r"-mcp==[0-9]+\.[0-9]+\.[0-9]+", pin or "")
        ):
            refuse("The installed plugin version or package pin is missing or malformed; reinstall the plugin.")
    if not shutil.which("uvx"):
        refuse("uvx is required; install uv from https://astral.sh/uv/install.sh and rerun.")
    if not shutil.which(target):
        refuse("The selected client CLI is missing from PATH; install it and rerun.")
    if target == "claude":
        claude_main(args, root, name, product)
        return
    if target == "codex":
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
    previous_env = prior.get("env", {})
    env_map(previous_env)
    if args.check:
        merge_env(previous_env, {}, product)
        print("Prerequisites passed: uvx, setup runtime, client and configuration shape checked.")
        return
    if args.refresh and (name not in servers or not previous_env):
        refuse("No saved Codex environment to refresh; run ordinary setup from the installed plugin first.")
    raw_input = "{}" if args.refresh else sys.stdin.buffer.read().decode("utf-8-sig")
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
    if not patch and not args.refresh:
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
            if target == "codex":
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
                        pin,
                    ],
                    environment,
                )
                client(["codex", "mcp", "remove", name], environment)
                entry = dict(prior)
                for key in ("url", "bearer_token_env_var", "http_headers", "env_http_headers"):
                    entry.pop(key, None)
                entry.update(command="uvx", args=["--python-preference", "system", pin], env=merged)
                # Replace our previous annotation rather than accumulating stale versions.
                annotation = "# unifi-plugin-setup: " + name + " "
                staged.write_text(
                    "\n".join(
                        line
                        for line in staged.read_text(encoding="utf-8").splitlines()
                        if not line.startswith(annotation)
                    )
                    + "\n",
                    encoding="utf-8",
                )
                with staged.open("a", encoding="utf-8") as handle:
                    handle.write("\n" + annotation + "plugin " + plugin_version + "; package " + pin + "\n")
                    handle.write("[mcp_servers." + json.dumps(name) + "]\n")
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
    if target == "codex":
        print("Codex pinned package: " + pin + " (plugin " + plugin_version + ").")
        print(
            "After every plugin upgrade, rerun the new plugin's set-env.sh --target codex --refresh "
            "or set-env.ps1 -Target codex -Refresh, then restart Codex."
        )
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
