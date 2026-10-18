#!/usr/bin/env python3
"""Private staging and atomic publication for the three plugin setup wrappers.

Values enter on stdin only. Never execute credential providers. Codex setup starts
the plugin's server once without any settings, so it reads no credentials and
contacts no controller.
Client output and exception text are deliberately excluded from diagnostics.
Claude Code options are saved through its own CLI. Codex and OpenClaw settings go
to a private per-user file that the plugin's bundled server reads.
"""

import argparse
import contextlib
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
import threading
import tomllib
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


KEY_PART = r"(?:\"(?:[^\"\\]|\\.)*\"|'[^']*'|[A-Za-z0-9_-]+)"


def table_path(line):
    """Decode a table or array-table path using TOML's quoted-key rules."""
    match = re.fullmatch(r"\s*(\[\[?)\s*(" + KEY_PART + r"(?:\s*\.\s*" + KEY_PART + r")*)\s*(\]\]?)\s*(?:#.*)?", line)
    if not match or len(match[1]) != len(match[3]):
        return None
    return [next(iter(tomllib.loads(part + " = 0"))) for part in re.findall(KEY_PART, match[2])]


def toml_lines(text):
    """Yield physical lines with headers only outside strings and containers.

    The complete document is parsed by tomllib before editing and again before
    publication; this lexer only identifies safe table boundaries in that text.
    """
    quote, depth = None, 0
    for line in text.split("\n"):
        line = line.removesuffix("\r")
        standalone = quote is None and depth == 0
        yield line, table_path(line) if standalone else None, standalone
        index = 0
        while index < len(line):
            char = line[index]
            if quote:
                if quote[0] == '"' and char == "\\":
                    index += 2
                    continue
                if line.startswith(quote, index):
                    index += len(quote)
                    if len(quote) == 3:
                        # Four/five closing quotes include literal quote content.
                        while index < len(line) and line[index] == quote[0]:
                            index += 1
                    quote = None
                    continue
            elif char == "#":
                break
            elif char in "\"'":
                quote = char * 3 if line.startswith(char * 3, index) else char
                index += len(quote)
                continue
            elif char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
            index += 1
    if quote is not None or depth:
        raise ValueError("Unsupported TOML lexical layout")


def remove_codex_entry(text, name):
    """Drop one server's tables from the config text; comments and layout elsewhere stay as written."""
    eol = "\r\n" if "\r\n" in text else "\n"
    # Older setup versions left a pin note above the entry; drop it with the entry.
    note = "# unifi-plugin-setup: " + name + " "
    lines, trailing, skipping = [], [], False

    def flush():
        # Comments after the removed tables belong to whatever follows them.
        while trailing and not trailing[0].strip():
            trailing.pop(0)
        lines.extend(line for line in trailing if not line.startswith(note))
        trailing.clear()

    for line, path, standalone in toml_lines(text):
        if path is not None:
            flush()
            skipping = path[:2] == ["mcp_servers", name]
        if not skipping:
            if not (standalone and line.startswith(note)):
                lines.append(line)
        elif standalone and (not line.strip() or line.lstrip().startswith("#")):
            trailing.append(line)
        else:
            trailing.clear()
    flush()
    return eol.join(lines).rstrip() + eol


def read_config(path, target):
    raw = path.read_bytes() if path.exists() else None
    if target == "codex":
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


# A normalized PEP 440 release with optional pre-release, post, dev and local parts,
# for example 0.37.0, 0.37.1.dev83 and 0.37.1.dev83+ge51932dd.
PEP440_VERSION = (
    r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?"
    r"(?:\+[a-z0-9]+(?:\.[a-z0-9]+)*)?"
)


def settings_path(product):
    """The per-user file the plugin's bundled server reads through UNIFI_SETTINGS_FILE (Codex and OpenClaw).

    Path.home() is %USERPROFILE% on Windows, matching the server's expansion of ~.
    """
    return Path.home() / ".config" / "unifi-mcp" / (product.lower() + ".env")


def read_settings(path):
    """Parse the settings file as the server does, refusing anything it would skip."""
    if path.is_symlink():
        refuse("The settings file is a symlink; replace it with a regular file and rerun.")
    if not path.exists():
        return None
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        refuse("The settings file cannot be read as UTF-8; repair or remove it and rerun.")
    settings = {}
    # Split on "\n" only, as the server does; settings_text refuses other line boundaries.
    for number, line in enumerate(text.split("\n"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not re.fullmatch(r"UNIFI_[A-Z][A-Z0-9_]*", key) or key in settings:
            refuse(f"Line {number} of the settings file is not a unique UNIFI_ setting; repair it and rerun.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        settings[key] = value
    return settings


def settings_text(settings, name):
    lines = [
        "# " + name + " settings for Codex and OpenClaw, written by the plugin's setup. The plugin's server reads",
        "# this file through UNIFI_SETTINGS_FILE; keep it readable by you only. Values are literal.",
    ]
    for key, value in settings.items():
        # Any line boundary a reader might honour (\x85 and \u2028 included) would split the value.
        if "\0" in value or len(("|" + value + "|").splitlines()) != 1:
            refuse("Settings file values must be single lines; correct the value and rerun.")
        # The server strips one pair of matching quotes, so quoting keeps every value exact.
        lines.append(key + '="' + value + '"')
    return "\n".join(lines) + "\n"


def write_private(path, data):
    """Atomically replace *path* with *data*, created readable by the current user only."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staged = path.with_name("." + path.name + ".unifi-setup-" + str(os.getpid()))
    staged.unlink(missing_ok=True)
    try:
        descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def shadow_notice(name, path, client):
    return (
        "Notice: " + client.label + " has an MCP entry for " + name + " that takes precedence over the plugin's "
        "own server (setup before plugin 1.0.0 wrote it), so plugin upgrades do not reach the server. Run "
        "set-env.sh --target "
        + client.target
        + " --refresh once (PowerShell: set-env.ps1 -Target "
        + client.target
        + " -Refresh): it moves the entry's settings into "
        + str(path)
        + " and removes the entry, without asking for credentials."
    )


def package_pin(root, name, *, bundled=False):
    """The package pin of the server the client runs: the bundled entry, else Claude Code's inline one."""
    files = (root / ".claude-plugin/plugin.json",)
    if bundled:
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
# system keychain); the manifest's inline mcpServers maps each option onto one variable.
# A configured sensitive option whose value Claude never reveals. NUL cannot occur
# in a real value: patches refuse it.
KEYCHAIN = "\0claude-keychain\0"
TRUTHY = ("true", "1", "yes", "on")
FALSY = ("false", "0", "no", "off")
# The newest Claude Code known to keep a keychain-held option when sent an empty
# value; configure and the options dialog cannot clear it, only uninstalling can.
KEEPS_KEYCHAIN_SECRETS = (2, 1, 296)


def claude_options(root):
    """Return {variable: option} and the option schema from the installed plugin."""
    try:
        manifest = json_object((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        schema, servers = manifest.get("userConfig"), manifest.get("mcpServers")
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


def claude_version(environment):
    """Claude Code's release as a tuple, or None when its output is unrecognized."""
    output = client(["claude", "--version"], environment).decode("utf-8", "replace")
    match = re.match(r"\s*([0-9]+)\.([0-9]+)\.([0-9]+)", output)
    return tuple(int(part) for part in match.groups()) if match else None


def keychain_cleared(saved, changes, mapping, schema):
    """Variables held in the keychain that *changes* would clear."""
    return sorted(
        variable
        for variable, option in mapping.items()
        if schema[option].get("sensitive") and saved.get(variable) == KEYCHAIN and changes.get(option) == ""
    )


def keychain_choices(plugin_id, saved, patch, mapping, schema, cleared):
    """The working choices, naming the options an uninstall would also clear."""
    reenter = sorted(
        variable
        for variable, value in saved.items()
        if variable not in cleared and variable not in patch and value != option_default(schema[mapping[variable]])
    )
    return (
        "Keep the saved secret by not switching, or run claude plugin uninstall "
        + plugin_id
        + " and claude plugin install "
        + plugin_id
        + ", then rerun setup with the provider. Uninstalling clears every option of the plugin"
        + ("; set these again too: " + ", ".join(reenter) if reenter else "")
        + ". Values are omitted."
    )


def auto_confirm_notice(env, product, deprecated_client=False):
    """Name a UNIFI_AUTO_CONFIRM carried in *env*, never its value."""
    value = env.get("UNIFI_AUTO_CONFIRM", "").strip()
    if not value:
        return None
    lead = "Notice: UNIFI_AUTO_CONFIRM is deprecated and is still set"
    lead += " in .claude/settings.local.json. " if deprecated_client else ". "
    if value.lower() in ("true", "1", "yes", "on"):
        return (
            lead + "Its current value turns on bypass: mutations run without confirmation unless a permission mode "
            f"is set. Set UNIFI_TOOL_PERMISSION_MODE=bypass (or UNIFI_{product}_TOOL_PERMISSION_MODE=bypass for "
            "this server only) instead, then remove UNIFI_AUTO_CONFIRM. Values are omitted."
        )
    return (
        lead + "Its current value does not enable bypass, so it has no effect and can be removed. Values are omitted."
    )


def other_prefixes(product):
    others = tuple(f"UNIFI_{p}_" for p in ("NETWORK", "PROTECT", "ACCESS") if p != product)
    return others + tuple(f"UNIFI_POLICY_{p}_" for p in ("NETWORK", "PROTECT", "ACCESS") if p != product)


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
    others = other_prefixes(product)
    owned = {k: v for k, v in env.items() if k.startswith((f"UNIFI_{product}_", f"UNIFI_POLICY_{product}_"))}
    shared = {k: v for k, v in env.items() if k.startswith("UNIFI_") and k not in owned and not k.startswith(others)}
    return path, data, owned, shared


def shared_name(variable, product):
    for prefix in (f"UNIFI_{product}_", f"UNIFI_POLICY_{product}_"):
        if variable.startswith(prefix):
            return prefix.replace(f"{product}_", "") + variable[len(prefix) :]
    return variable


def option_conflicts(saved, patch, mapping, schema, product):
    """Name connection variables whose saved options (from any project) differ from *patch*."""
    if not saved.get(f"UNIFI_{product}_HOST"):
        return []
    conflicts = []
    for field in ("HOST", "USERNAME", "PORT", "SITE"):
        variable = f"UNIFI_{product}_{field}"
        # An empty saved option is filled, not replaced; defaults such as port 443 are held values.
        current = saved.get(variable, "")
        if variable in mapping and variable in patch and current:
            if option_text(schema[mapping[variable]], patch[variable]) != current:
                conflicts.append(variable)
    return conflicts


def recovery(name):
    # A session keeps the options it started with: /mcp reconnect alone restarts
    # the server with those, so new options need /reload-plugins or a new session.
    return (
        "run /reload-plugins (/mcp reconnect alone keeps the options the session started with; use /mcp reconnect "
        "plugin:" + name + ":" + name + " only if /mcp shows the server as failed)"
    )


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
        try:
            conflicts = option_conflicts(saved, legacy_patch(owned, shared, mapping, product), mapping, schema, product)
        except SetupError:
            conflicts = []  # The migration itself reports a malformed legacy value.
        if conflicts:
            notice += (
                " They differ from the plugin options saved from another project (" + ", ".join(conflicts) + "), "
                "which this project now uses. Add --replace (PowerShell: -Replace) to make this project's settings "
                "the options for every project, or remove the leftover keys to keep the saved options."
            )
    auto_notice = auto_confirm_notice(shared, product, deprecated_client=True) if legacy_data else None
    if args.check:
        merge_env(saved, {}, product, inherited)
        if notice:
            print(notice)
        others_left = [k for k in legacy_data["env"] if k.startswith(other_prefixes(product))] if legacy_data else []
        if shared and not owned and not others_left:
            print(
                "Notice: no UniFi plugin settings remain in .claude/settings.local.json, but it still holds shared "
                "settings (" + ", ".join(sorted(shared)) + "). Claude Code still exports them into every process "
                "it starts in this project, including shell commands and MCP servers. Remove them once no "
                "standalone server or older plugin relies on them. Values are omitted."
            )
        if auto_notice:
            print(auto_notice)
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
        replaced = option_conflicts(saved, patch, mapping, schema, product)
        if replaced and not args.replace:
            refuse(
                "This project's legacy settings differ from the plugin options already saved from another project: "
                + ", ".join(replaced)
                + ". Plugin options apply in every project. Rerun with --replace (PowerShell: -Replace) to make "
                "this project's settings the options for every project, or remove this plugin's keys from "
                ".claude/settings.local.json to keep the saved options. No settings were changed."
            )
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
    if "UNIFI_AUTO_CONFIRM" in patch:
        refuse(
            "UNIFI_AUTO_CONFIRM is deprecated and has no Claude Code option. Set "
            f"UNIFI_{product}_TOOL_PERMISSION_MODE instead; no settings were changed."
        )
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
    cleared = keychain_cleared(saved, changes, mapping, schema)
    choices = keychain_choices(plugin_id, saved, patch, mapping, schema, cleared)

    def kept_message(kept, outcome):
        return (
            "Claude Code kept " + ", ".join(kept) + " in the system keychain instead of clearing it; this Claude "
            "Code version cannot clear a saved secret through claude plugin configure or the /plugin options "
            "dialog. " + outcome + " " + choices
        )

    # Clear a keychain secret alone first on a release newer than the newest known
    # to keep it: where Claude Code ignores the empty value, nothing changes.
    probe = False
    if cleared:
        version = claude_version(environment)
        probe = version is None or version > KEEPS_KEYCHAIN_SECRETS
        if not probe:
            refuse(
                "Claude Code holds " + ", ".join(cleared) + " in the system keychain, and this Claude Code version "
                "cannot clear a saved secret: claude plugin configure and the /plugin options dialog ignore an "
                "empty value. No settings were changed. " + choices
            )
    if args.dry_run:
        print("Validation passed; dry run made no changes. Values are omitted.")
        if auto_notice:
            print(auto_notice)
        return
    remaining = None
    if args.migrate:
        # We verify only this installation's options. Other products (including
        # older plugins or standalone servers) can use shared fallbacks without
        # leaving scoped keys here, so absence of those keys proves nothing.
        others_left = sorted(k for k in legacy_data["env"] if k.startswith(other_prefixes(product)))
        removed = set(owned)
        remaining = dict(legacy_data)
        remaining["env"] = {k: v for k, v in legacy_data["env"].items() if k not in removed}
        original = legacy_path.read_bytes()
    if claude_saved(plugin_id, environment, mapping, schema) != saved:
        refuse("The plugin's options changed during setup; rerun against the latest options.")

    def configure(values):
        client(
            ["claude", "plugin", "configure", plugin_id, "--values-stdin"],
            environment,
            json.dumps(values, ensure_ascii=False).encode("utf-8"),
        )

    if changes:
        cleared_note = ""
        if probe:
            configure({mapping[variable]: "" for variable in cleared})
            current = claude_saved(plugin_id, environment, mapping, schema)
            kept = [variable for variable in cleared if current.get(variable) == KEYCHAIN]
            if kept:
                refuse(kept_message(kept, "No settings were changed."))
            cleared_note = (
                " " + ", ".join(cleared) + (" was" if len(cleared) == 1 else " were") + " cleared from the system "
                "keychain; rerun setup to finish."
            )
        try:
            configure(changes)
        except SetupError:
            if probe:
                refuse("Claude Code did not save the requested options." + cleared_note)
            raise
        after = claude_values(claude_saved(plugin_id, environment, mapping, schema), mapping, schema)
        retained = all(
            (after[option] == KEYCHAIN) == bool(value) if schema[option].get("sensitive") else after[option] == value
            for option, value in changes.items()
        )
        if not retained:
            restore = {o: before[o] for o in changes if before[o] != KEYCHAIN and not schema[o].get("sensitive")}
            if restore:
                configure(restore)
            kept = sorted(
                variable
                for variable, option in mapping.items()
                if schema[option].get("sensitive") and changes.get(option) == "" and after[option] == KEYCHAIN
            )
            if kept:
                refuse(kept_message(kept, "Previous non-secret options were restored."))
            refuse(
                "Claude Code did not retain the requested options; previous non-secret options were restored."
                + cleared_note
            )
    if remaining is not None:
        replace_project_settings(legacy_path, original, remaining)
    if args.migrate:
        print(
            "Migrated " + ", ".join(sorted(k for k in owned if k in patch)) + " into the plugin's Claude Code options "
            "and removed " + ", ".join(sorted(removed)) + " from .claude/settings.local.json. Values are omitted."
        )
        if replaced:
            print(
                "Replaced the plugin options saved from another project (" + ", ".join(replaced) + "); they now "
                "apply in every project."
            )
        dropped = sorted(k for k in owned if k not in patch)
        if dropped:
            print("Not migrated (no Claude Code option): " + ", ".join(dropped) + ".")
        kept = sorted(set(shared) - removed)
        if kept:
            print(
                "Shared settings kept in .claude/settings.local.json because other consumers have not been verified "
                "as migrated (only this plugin's options were checked): " + ", ".join(kept) + ". "
                "A product using only shared fallbacks leaves no product-prefixed keys. "
                "Remove shared settings only after verifying every consumer no longer needs them."
            )
            if others_left:
                print("Other product settings also remain: " + ", ".join(others_left) + ".")
    elif notice:
        print(notice)
    if auto_notice:
        print(auto_notice)
    print(
        "Claude Code plugin options saved for "
        + plugin_id
        + ". In an open Claude Code session, "
        + recovery(name)
        + ". A new session also loads them. Values are omitted."
    )


class CodexClient:
    """config.toml, where setup before plugin 1.0.0 wrote a [mcp_servers.<plugin>] entry."""

    target, name, label = "codex", "Codex", "config.toml"

    def __init__(self):
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().absolute()
        self.config = home / "config.toml"

    def read(self):
        return read_config(self.config, "codex")

    def remove(self, name, original, data, servers):
        """Drop the entry, keeping a private backup; returns the backup and whether Codex rewrote the file."""
        config, rewritten = self.config, False
        config_lock = config.with_name(config.name + ".setup-lock")
        try:
            config_lock.mkdir(mode=0o700)
        except FileExistsError:
            refuse(
                "Settings were saved, but config.toml setup is locked. If no setup is running, remove the "
                "adjacent .setup-lock directory and rerun to remove the " + name + " entry."
            )
        try:
            expected = dict(data, mcp_servers={k: v for k, v in servers.items() if k != name})

            def matches(candidate):
                try:
                    document = tomllib.loads(candidate.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return False
                return document == expected or (
                    not expected["mcp_servers"] and dict(document, mcp_servers={}) == expected
                )

            try:
                edited = remove_codex_entry(original.decode("utf-8"), name).encode("utf-8")
            except Exception:
                # A scanner limitation must not prevent the supported CLI
                # path. Never expose its potentially sensitive error.
                edited = None
            if edited is None or not matches(edited):
                # An unusual layout (dotted or inline mcp_servers keys): let Codex remove the entry
                # in a private copy, which drops comments inside MCP server tables.
                with tempfile.TemporaryDirectory(prefix=".unifi-setup-", dir=config.parent) as temporary:
                    stage = Path(temporary)
                    (stage / "config.toml").write_bytes(original)
                    environment = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_")}
                    environment.update(HOME=str(stage), USERPROFILE=str(stage), CODEX_HOME=str(stage))
                    client(["codex", "mcp", "remove", name], environment)
                    edited = (stage / "config.toml").read_bytes()
                rewritten = True
                if not matches(edited):
                    refuse(
                        "Settings were saved, but setup could not remove the " + name + " entry from "
                        "config.toml safely; remove it with codex mcp remove " + name + "."
                    )
            if config.read_bytes() != original:
                refuse("config.toml changed during setup; settings were saved, rerun to remove the entry.")
            backup = backup_path(config, name)
            write_private(backup, original)
            write_private(config, edited)
        finally:
            config_lock.rmdir()
        notes = []
        if rewritten:
            notes.append(
                "Notice: this config.toml lays out its MCP servers in a form setup cannot edit in place, so "
                "Codex rewrote it and dropped the comments inside MCP server tables."
            )
        return backup, notes

    def loaded(self, removed):
        return "Restart Codex to load the settings."

    def warm(self, root, name):
        # The settings are saved and reported before the server starts.
        sys.stdout.flush()
        print(warm_up(root, name), flush=True)


class OpenClawClient:
    """openclaw.json, where setup before plugin 1.0.0 wrote an mcp.servers.<plugin> entry."""

    target, name, label = "openclaw", "OpenClaw", "openclaw.json"

    def __init__(self):
        state = Path(os.environ.get("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw")))
        self.config = Path(os.environ.get("OPENCLAW_CONFIG_PATH", str(state / "openclaw.json"))).expanduser().absolute()

    def read(self):
        return read_config(self.config, "openclaw")

    def remove(self, name, original, data, servers):
        """Remove the entry with OpenClaw's own CLI after a private backup."""
        config = self.config
        config_lock = config.with_name(config.name + ".setup-lock")
        try:
            config_lock.mkdir(mode=0o700)
        except FileExistsError:
            refuse(
                "Settings were saved, but openclaw.json setup is locked. If no setup is running, remove the "
                "adjacent .setup-lock directory and rerun to remove the " + name + " entry."
            )
        try:
            if config.read_bytes() != original:
                refuse("openclaw.json changed during setup; settings were saved, rerun to remove the entry.")
            backup = backup_path(config, name)
            write_private(backup, original)
            environment = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_")}
            unremoved = (
                "Settings were saved, but OpenClaw did not remove only the " + name + " entry. Compare "
                "openclaw.json with " + str(backup) + " and remove the entry with openclaw mcp unset " + name + "."
            )
            try:
                client(["openclaw", "mcp", "unset", name], environment)
                _, _, remaining = read_config(config, "openclaw")
            except SetupError:
                refuse(unremoved)
            if remaining != {k: v for k, v in servers.items() if k != name}:
                refuse(unremoved)
        finally:
            config_lock.rmdir()
        return backup, []

    def loaded(self, removed):
        if removed:
            # Removing the entry changes openclaw.json, which a running gateway reloads.
            return "OpenClaw starts the plugin's server with these settings at its next agent turn."
        # openclaw.json is unchanged, so an open session keeps the unconfigured server.
        return (
            "Start a new OpenClaw session or run openclaw gateway restart to load the settings; a session that is "
            "already open keeps the unconfigured server."
        )

    def warm(self, root, name):
        pass


def backup_path(config, name):
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    return config.with_name(config.name + ".bak-" + name + "-" + stamp)


# The variables Codex passes from its own environment to a plugin's stdio server
# (its core list and the CA bundle uv reads), so uvx uses the same cache and Python.
CODEX_SERVER_ENV = (
    "PATH PATHEXT SHELL COMSPEC SYSTEMROOT WINDIR SYSTEMDRIVE USERNAME USERDOMAIN USERPROFILE HOMEDRIVE HOMEPATH "
    "PROGRAMFILES PROGRAMFILES(X86) PROGRAMW6432 PROGRAMDATA LOCALAPPDATA APPDATA TEMP TMP TMPDIR POWERSHELL PWSH"
    if os.name == "nt"
    else "HOME LOGNAME PATH SHELL USER __CF_USER_TEXT_ENCODING LANG LC_ALL TERM TMPDIR TZ"
).split() + ["SSL_CERT_FILE"]
WARM_UP_SECONDS = 60
# Its own process group, so stopping it also stops what uvx started.
OWN_GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}


def warm_up(root, name, timeout=WARM_UP_SECONDS):
    """Start the plugin's server once, as Codex launches it, and stop it after it answers initialize.

    The first launch of a server version builds and compiles its environment, which
    takes longer than Codex waits for plugin servers before a session's first request.
    The server gets no settings file and no UNIFI_ variables, so it starts in setup
    mode: it reads no credentials and contacts no controller. Returns a one-line note
    and never raises; server output is discarded.
    """
    pin = package_pin(root, name, bundled=True)
    failed = (
        "Notice: " + pin + " did not start ahead of Codex; the settings are saved, but Codex's first session "
        "may start without the " + name + " tools."
    )
    environment = {key: os.environ[key] for key in CODEX_SERVER_ENV if os.environ.get(key)}
    try:
        entry = json_object((root / ".mcp.codex.json").read_text(encoding="utf-8"))["mcpServers"][name]
        command = [entry["command"], *entry["args"]]
        executable = shutil.which(command[0], path=environment.get("PATH"))
        if executable is None or not all(isinstance(part, str) for part in command):
            return failed
        process = subprocess.Popen(
            [executable, *command[1:]],
            cwd=root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            **OWN_GROUP,
        )
    except Exception:
        return failed
    answered = threading.Event()

    def read_reply():
        # At most 1 MiB is read; the reply is the first line with the request's id.
        for _ in range(16):
            line = process.stdout.readline(65536)
            if not line:
                return
            try:
                if json.loads(line).get("id") == 1:
                    answered.set()
                    return
            except (ValueError, AttributeError):
                continue

    try:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": name + "-setup", "version": "1"},
            },
        }
        reader = threading.Thread(target=read_reply, daemon=True)
        reader.start()
        process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        process.stdin.flush()
        reader.join(timeout)
    except OSError:
        pass  # The server exited before reading the request.
    finally:
        stop(process)
    if not answered.is_set():
        return failed
    return "Started " + pin + " once, so Codex's next session starts it quickly."


def stop(process):
    """End a stdio server as an MCP client does: close its input, then terminate, then kill."""
    steps = [process.stdin.close]
    if os.name == "nt":
        steps.append(process.kill)
    else:
        steps += [lambda: os.killpg(process.pid, signal.SIGTERM), lambda: os.killpg(process.pid, signal.SIGKILL)]
    for step in steps:
        with contextlib.suppress(OSError):
            step()
        try:
            process.wait(5)
            break
        except subprocess.TimeoutExpired:
            continue
    with contextlib.suppress(OSError):
        process.stdout.close()


def bundled_main(args, root, name, product, patch, client):
    """Save settings in the per-user file the bundled server reads and retire a shadowing client entry."""
    path = settings_path(product)
    saved = read_settings(path)
    if client.config.is_symlink():
        refuse("Configuration symlinks are unsupported; use the client editor for this installation.")
    original, data, servers = client.read()
    entry = servers.get(name)
    if entry is not None and not isinstance(entry, dict):
        refuse("The existing MCP server must be an object; repair it and rerun.")
    # Only UNIFI_ settings move; the rest of an entry stays in the configuration backup.
    entry_env = env_map(entry.get("env", {})) if entry else {}
    carried = {k: v for k, v in entry_env.items() if k.startswith("UNIFI_")}
    left = sorted("env " + k for k in entry_env if k not in carried)
    left += sorted("entry setting " + k for k in (entry or {}) if k not in ("command", "args", "env"))
    if entry is not None and saved is not None and saved != carried:
        refuse(
            "Both " + str(path) + " and a " + client.label + " entry for " + name + " hold settings, and they "
            "differ. Delete the settings file to keep the entry's settings, or remove the entry with "
            + ("codex mcp remove " if client.target == "codex" else "openclaw mcp unset ")
            + name
            + " to keep the file's, then rerun. Nothing was changed."
        )
    base = carried if entry is not None else (saved or {})
    if args.check:
        merge_env(base, {}, product)
        if entry is not None:
            print(shadow_notice(name, path, client))
        elif saved is not None and os.name != "nt" and path.stat().st_mode & 0o077:
            print("Notice: " + str(path) + " is readable by other users; rerun setup or chmod 600 it.")
        print("Prerequisites passed: uvx, setup runtime, client and configuration shape checked.")
        return
    if args.refresh and entry is None:
        if saved is None:
            refuse(
                "No saved " + client.name + " settings to convert; run ordinary setup from the installed plugin first."
            )
        print(
            "Nothing to convert: "
            + client.label
            + " has no entry for "
            + name
            + "; settings live in "
            + str(path)
            + "."
        )
        client.warm(root, name)
        return
    merged = merge_env(base, patch, product)
    text = settings_text(merged, name).encode("utf-8")
    auto_notice = auto_confirm_notice(merged, product)
    if args.dry_run:
        print("Validation passed; dry run made no changes. Values are omitted.")
        if auto_notice:
            print(auto_notice)
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Cooperating setup calls serialize; a killed process leaves a harmless lock.
    lock = path.with_name("." + path.name + ".setup-lock")
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        refuse("Setup is locked. If no setup is running, remove the adjacent .setup-lock directory and rerun.")
    backup, notes = None, []
    try:
        if read_settings(path) != saved:
            refuse("Settings changed during setup; rerun against the latest settings.")
        # The file first: if the entry removal then fails, a rerun finds matching settings.
        write_private(path, text)
        if entry is not None:
            backup, notes = client.remove(name, original, data, servers)
    finally:
        lock.rmdir()
    print(
        "Saved the " + client.name + " settings for " + name + " to " + str(path) + ", readable by you only. The "
        "plugin's own server (" + package_pin(root, name, bundled=True) + ") reads this file, so plugin upgrades "
        "need no setup."
    )
    if entry is not None:
        print(
            "Moved the settings of the " + name + " entry in " + client.label + " into that file and removed the "
            "entry, which took precedence over the plugin's server. Previous " + client.label + ": " + str(backup) + "."
        )
        if left:
            print("Not moved (names only; they remain in the backup): " + ", ".join(left) + ".")
        for note in notes:
            print(note)
    if auto_notice:
        print(auto_notice)
    print(client.loaded(entry is not None) + " Values are omitted.")
    client.warm(root, name)


def read_patch(args):
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
    return patch


def main():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            refuse("Unsupported setup arguments; choose claude, codex or openclaw.")

    parser = SafeParser(description=__doc__)
    parser.add_argument("--target", choices=("claude", "codex", "openclaw"), default="claude")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--pairs", action="store_true")
    parser.add_argument(
        "--refresh", action="store_true", help="Move a pre-1.0.0 client entry's settings into the settings file"
    )
    parser.add_argument(
        "--migrate", action="store_true", help="Move legacy Claude project settings into plugin options"
    )
    parser.add_argument(
        "--replace", action="store_true", help="Let a migration replace differing options saved from another project"
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
    if args.refresh and (target == "claude" or args.pairs or args.check):
        refuse("Refresh is only supported for Codex and OpenClaw, without environment arguments.")
    if args.migrate and (target != "claude" or args.pairs or args.check):
        refuse("Migration is only supported for Claude Code, without environment arguments.")
    if args.replace and not args.migrate:
        refuse("--replace is only supported together with --migrate.")
    if not shutil.which("uvx"):
        refuse("uvx is required; install uv from https://astral.sh/uv/install.sh and rerun.")
    if not shutil.which(target):
        refuse("The selected client CLI is missing from PATH; install it and rerun.")
    if target == "claude":
        claude_main(args, root, name, product)
        return
    bundled_main(
        args,
        root,
        name,
        product,
        {} if args.check or args.refresh else read_patch(args),
        CodexClient() if target == "codex" else OpenClawClient(),
    )


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
