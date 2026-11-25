"""The Codex settings file that setup writes reads back exactly under the server's dotenv rules."""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
PRODUCTS = ("network", "protect", "access", "sitemanager", "drive")
NON_ASCII = "é中 😀﻿\U0010ffff"


def load_setup_config(product: str):
    path = PLUGINS / f"unifi-{product}" / "scripts" / "setup_config.py"
    spec = importlib.util.spec_from_file_location(f"setup_config_{product}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract_read(text: str) -> dict[str, str]:
    """The server's documented format: KEY=VALUE, # comments, one pair of matching quotes stripped."""
    settings = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        settings[key.strip()] = value
    return settings


@pytest.mark.parametrize("product", PRODUCTS)
def test_random_single_line_values_round_trip(tmp_path: Path, product: str) -> None:
    module = load_setup_config(product)
    rng = random.Random(20261011)
    alphabet = ['"', "'", "\\", "\t", "\x7f", "a", " ", "#", "=", "$", "{", *NON_ASCII]
    for _ in range(2000):
        settings = {
            f"UNIFI_FIXTURE_{index}": "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))
            for index in range(3)
        }
        text = module.settings_text(settings, f"unifi-{product}")
        assert contract_read(text) == settings
        path = tmp_path / "settings.env"
        path.write_text(text, encoding="utf-8")
        assert module.read_settings(path) == settings


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize(
    "value", ["two\nlines", "carriage\rreturn", "nul\0byte", "next\x85line", "line\u2028sep", "form\x0cfeed"]
)
def test_multi_line_values_are_refused(product: str, value: str) -> None:
    module = load_setup_config(product)
    with pytest.raises(module.SetupError):
        module.settings_text({"UNIFI_FIXTURE": value}, f"unifi-{product}")


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("line", ["export UNIFI_HOST=x", "OTHER=x", "UNIFI_HOST", "UNIFI_HOST=a\nUNIFI_HOST=b"])
def test_lines_the_server_would_skip_are_refused(tmp_path: Path, product: str, line: str) -> None:
    module = load_setup_config(product)
    path = tmp_path / "settings.env"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(module.SetupError):
        module.read_settings(path)


@pytest.mark.parametrize("product", PRODUCTS)
def test_settings_file_follows_the_server_contract_path(product: str) -> None:
    module = load_setup_config(product)
    assert module.settings_path(product.upper()) == Path.home() / ".config" / "unifi-mcp" / f"{product}.env"


def test_the_plugin_copies_are_identical() -> None:
    copies = {(PLUGINS / f"unifi-{product}" / "scripts" / "setup_config.py").read_bytes() for product in PRODUCTS}
    assert len(copies) == 1


@pytest.mark.parametrize(
    "key",
    [
        "UNIFI_SITEMANAGER_" + suffix
        for suffix in (
            "HOST",
            "USERNAME",
            "PASSWORD",
            "PASSWORD_FILE",
            "PASSWORD_COMMAND",
            "PORT",
            "SITE",
            "VERIFY_SSL",
            "SSL_FINGERPRINT",
            "API_SSL_FINGERPRINT",
            "TOOL_PERMISSION_MODE",
            "API_KEY_EXEC",
        )
    ]
    + [
        "UNIFI_API_KEY",
        "UNIFI_API_KEY_FILE",
        "UNIFI_API_KEY_COMMAND",
        "UNIFI_SETTINGS_FILE",
        "UNIFI_ACCESS_API_KEY",
        "UNIFI_NETWORK_API_KEY",
        "UNIFI_PROTECT_API_KEY",
        "UNIFI_PASSWORD",
        "UNIFI_HOST",
        "UNIFI_POLICY_SITEMANAGER_CREATE",
        "UNIFI_POLICY_SITEMANAGER_UPDATE",
        "UNIFI_POLICY_SITEMANAGER_DELETE",
        "UNIFI_POLICY_CREATE",
        "UNIFI_TOOL_PERMISSION_MODE",
        "UNIFI_TOOL_REGISTRATION_MODE",
    ],
)
def test_cloud_setup_rejects_non_key_settings_even_when_deleting(key: str) -> None:
    module = load_setup_config("sitemanager")
    for value in ("FAKE-input", "", None):
        with pytest.raises(module.SetupError):
            module.merge_env({}, {key: value}, "SITEMANAGER", inherited={})
    with pytest.raises(module.SetupError):
        module.merge_env({key: "FAKE-existing"}, {}, "SITEMANAGER", inherited={})


@pytest.mark.parametrize("suffixes", [("", "_FILE"), ("", "_COMMAND"), ("_FILE", "_COMMAND")])
def test_cloud_setup_refuses_each_ambiguous_key_pair(tmp_path, suffixes) -> None:
    module = load_setup_config("sitemanager")
    path = tmp_path / "key"
    path.write_text("FAKE-key")
    import sys

    values = {"": "FAKE-key", "_FILE": str(path), "_COMMAND": sys.executable}
    patch = {"UNIFI_SITEMANAGER_API_KEY" + suffix: values[suffix] for suffix in suffixes}
    with pytest.raises(module.SetupError):
        module.merge_env({}, patch, "SITEMANAGER", inherited={})
    with pytest.raises(module.SetupError):
        module.merge_env({}, {}, "SITEMANAGER", inherited=patch)


def test_cloud_setup_ignores_shared_credentials_and_switches_only_its_own_source(tmp_path) -> None:
    module = load_setup_config("sitemanager")
    path = tmp_path / "key"
    path.write_text("FAKE-key")
    shared = {"UNIFI_API_KEY": "FAKE-console", "UNIFI_API_KEY_COMMAND": "missing-console-provider"}
    assert module.merge_env({}, {}, "SITEMANAGER", inherited=shared) == {}
    assert module.merge_env(
        {"UNIFI_SITEMANAGER_API_KEY": "FAKE-old"},
        {"UNIFI_SITEMANAGER_API_KEY_FILE": str(path)},
        "SITEMANAGER",
        inherited=shared,
    ) == {"UNIFI_SITEMANAGER_API_KEY_FILE": str(path)}


@pytest.mark.parametrize(
    "suffix,value", [("_FILE", "relative-key"), ("_FILE", "/missing-key"), ("_COMMAND", "missing-provider")]
)
def test_cloud_setup_validates_provider_references(suffix, value) -> None:
    module = load_setup_config("sitemanager")
    with pytest.raises(module.SetupError):
        module.merge_env({}, {"UNIFI_SITEMANAGER_API_KEY" + suffix: value}, "SITEMANAGER", inherited={})


def test_cloud_provider_validation_never_reads_or_executes_the_key(tmp_path, monkeypatch) -> None:
    import sys

    module = load_setup_config("sitemanager")
    path = tmp_path / "key"
    path.write_text("FAKE-provider-secret")

    def forbidden(*args, **kwargs):
        pytest.fail("Setup read or executed a credential provider")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(module.subprocess, "run", forbidden)
    assert module.merge_env({}, {"UNIFI_SITEMANAGER_API_KEY_FILE": str(path)}, "SITEMANAGER", inherited={}) == {
        "UNIFI_SITEMANAGER_API_KEY_FILE": str(path)
    }
    assert module.merge_env({}, {"UNIFI_SITEMANAGER_API_KEY_COMMAND": sys.executable}, "SITEMANAGER", inherited={}) == {
        "UNIFI_SITEMANAGER_API_KEY_COMMAND": sys.executable
    }


@pytest.mark.parametrize(
    "other", ["UNIFI_API_KEY", "UNIFI_NETWORK_API_KEY", "UNIFI_PROTECT_API_KEY", "UNIFI_ACCESS_API_KEY"]
)
def test_legacy_patch_cannot_migrate_console_credentials_to_cloud(other) -> None:
    module = load_setup_config("sitemanager")
    mapping = {"UNIFI_SITEMANAGER_API_KEY" + suffix: "api_key" + suffix.lower() for suffix in ("", "_FILE", "_COMMAND")}
    with pytest.raises(module.SetupError, match="Site Manager has no legacy console settings to migrate"):
        module.legacy_patch(
            {"UNIFI_SITEMANAGER_HOST": "FAKE-unused"}, {other: "FAKE-console-key"}, mapping, "SITEMANAGER"
        )


@pytest.mark.parametrize("product", ["network", "protect", "access"])
@pytest.mark.parametrize("case", ["missing_file", "unknown_suffix", "two_forms"])
def test_console_cloud_named_inputs_are_saved_unchanged(tmp_path, product, case) -> None:
    import copy

    # The helper released before the Site Manager bundle accepted each of these
    # inputs for a console product and saved it unchanged.
    missing = str(tmp_path / "missing-provider")
    patch = {
        "missing_file": {"UNIFI_SITEMANAGER_API_KEY_FILE": missing},
        "unknown_suffix": {"UNIFI_SITEMANAGER_API_KEY_X": "FAKE-opaque"},
        "two_forms": {"UNIFI_SITEMANAGER_API_KEY": "FAKE-opaque", "UNIFI_SITEMANAGER_API_KEY_FILE": missing},
    }[case]
    expected = copy.deepcopy(patch)
    module = load_setup_config(product)
    merged = module.merge_env({}, patch, product.upper(), inherited={})
    assert merged == expected
    # Exercise publication, not just admission: the same opaque inputs still save.
    settings = tmp_path / "console-settings"
    module.write_private(settings, module.settings_text(merged, f"unifi-{product}").encode())
    assert module.read_settings(settings) == expected


@pytest.mark.parametrize("product,other", [("NETWORK", "ACCESS"), ("PROTECT", "NETWORK"), ("ACCESS", "PROTECT")])
def test_console_legacy_settings_classify_cloud_keys_as_another_product(tmp_path, monkeypatch, product, other) -> None:
    import json

    module = load_setup_config(product.lower())
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    env = {
        f"UNIFI_{product}_HOST": "192.0.2.1",
        "UNIFI_SITEMANAGER_API_KEY": "FAKE-cloud-key",
        "UNIFI_SITEMANAGER_API_KEY_FILE": "FAKE-cloud-provider",
        f"UNIFI_{other}_HOST": "192.0.2.2",
        "UNIFI_API_KEY": "FAKE-shared-console-key",
    }
    (tmp_path / ".claude/settings.local.json").write_text(json.dumps({"env": env}))
    _, _, owned, shared = module.legacy_settings(product)
    assert owned == {f"UNIFI_{product}_HOST": "192.0.2.1"}
    assert shared == {"UNIFI_API_KEY": "FAKE-shared-console-key"}
    assert "UNIFI_SITEMANAGER_" in module.other_prefixes(product)
    # Even when an option map contains a cloud-looking variable, it is not offered.
    patch = module.legacy_patch(
        owned, shared, {f"UNIFI_{product}_HOST": "host", "UNIFI_SITEMANAGER_API_KEY": "extra"}, product
    )
    # No UNIFI_HOST to match, so the shared console key belongs to no host this plugin uses.
    assert patch == {f"UNIFI_{product}_HOST": "192.0.2.1"}
    assert module.unmigrated_shared_credentials(owned, shared, product) == ["UNIFI_API_KEY"]


@pytest.mark.parametrize(
    "legacy,saved,same",
    [
        ({"UNIFI_HOST": "192.0.2.1"}, {}, True),
        ({"UNIFI_PROTECT_HOST": "192.0.2.1", "UNIFI_HOST": "192.0.2.1"}, {}, True),
        ({"UNIFI_PROTECT_HOST": "Console.Example", "UNIFI_HOST": "console.example"}, {}, True),
        ({"UNIFI_PROTECT_HOST": "192.0.2.1", "UNIFI_HOST": "192.0.2.1", "UNIFI_PORT": "8443"}, {}, True),
        # After migration the plugin uses UNIFI_HOST as its host, whatever was saved before.
        ({"UNIFI_HOST": "192.0.2.1"}, {"UNIFI_PROTECT_HOST": "192.0.2.9"}, True),
        ({"UNIFI_HOST": "192.0.2.1"}, {"UNIFI_PROTECT_HOST": "192.0.2.1", "UNIFI_PROTECT_PORT": "443"}, True),
        # No UNIFI_HOST in these settings: the shared credentials were meant for a host they do not name.
        ({}, {}, False),
        ({}, {"UNIFI_PROTECT_HOST": "nvr.other"}, False),
        ({"UNIFI_PROTECT_HOST": "192.0.2.1"}, {}, False),
        ({"UNIFI_PROTECT_HOST": "192.0.2.1", "UNIFI_HOST": "192.0.2.2"}, {}, False),
        ({"UNIFI_PROTECT_HOST": " 192.0.2.1 ", "UNIFI_HOST": "192.0.2.1"}, {}, False),
        ({"UNIFI_PROTECT_HOST": "https://192.0.2.1", "UNIFI_HOST": "192.0.2.1"}, {}, False),
        ({"UNIFI_PROTECT_HOST": "192.0.2.1/", "UNIFI_HOST": "192.0.2.1"}, {}, False),
        ({"UNIFI_PROTECT_HOST": "192.0.2.1", "UNIFI_HOST": "192.0.2.1", "UNIFI_PROTECT_PORT": "7443"}, {}, False),
        # The saved port stays when these settings name none.
        ({"UNIFI_HOST": "192.0.2.1"}, {"UNIFI_PROTECT_HOST": "192.0.2.1", "UNIFI_PROTECT_PORT": "7443"}, False),
    ],
)
def test_migration_reuses_shared_credentials_only_for_the_shared_console(tmp_path, legacy, saved, same) -> None:
    module = load_setup_config("protect")
    owned = {k: v for k, v in legacy.items() if k.startswith("UNIFI_PROTECT_")}
    owned["UNIFI_PROTECT_SITE"] = "default"  # something of this plugin's own to migrate
    shared = {k: v for k, v in legacy.items() if k not in owned}
    provider = str(tmp_path / "provider")
    shared["UNIFI_USERNAME"] = "fake-user"
    shared["UNIFI_PASSWORD_FILE"] = provider
    mapping = {"UNIFI_PROTECT_HOST": "host", "UNIFI_PROTECT_USERNAME": "username", "UNIFI_PROTECT_SITE": "site"}
    patch = module.legacy_patch(owned, shared, mapping, "PROTECT", saved)
    carried = {"UNIFI_PROTECT_USERNAME": "fake-user", "UNIFI_PROTECT_PASSWORD_FILE": provider}
    assert {k: patch.get(k) for k in carried} == (carried if same else dict.fromkeys(carried))
    unmigrated = module.unmigrated_shared_credentials(owned, shared, "PROTECT", saved)
    assert unmigrated == ([] if same else ["UNIFI_USERNAME", "UNIFI_PASSWORD_FILE"])


# One table for the server's rule and the setup helper's copy of it: they cannot
# import each other, so this keeps them in step.
HOST_RULE = [
    ("console.invalid", "console.invalid", {}, True),
    ("Console.Invalid", "console.INVALID", {}, True),
    ("console.invalid", "console.invalid", {"UNIFI_PORT": "8443"}, True),
    ("console.invalid", "console.invalid", {"UNIFI_PORT": "8443", "UNIFI_PROTECT_PORT": "8443"}, True),
    ("console.invalid", "console.invalid", {"UNIFI_PROTECT_PORT": "443"}, True),
    ("console.invalid", "other.invalid", {}, False),
    ("", "console.invalid", {}, False),
    (" console.invalid ", "console.invalid", {}, False),
    ("console.invalid", "console.invalid\t", {}, False),
    ("  ", "  ", {}, False),
    ("\u00c4.invalid", "\u00e4.invalid", {}, False),
    ("console.invalid", "https://console.invalid", {}, False),
    ("console.invalid", "console.invalid/", {}, False),
    ("console.invalid", "console.invalid:443", {}, False),
    ("console.invalid", "console.invalid", {"UNIFI_PROTECT_PORT": "7443"}, False),
    ("console.invalid", "console.invalid", {"UNIFI_PORT": "8443", "UNIFI_PROTECT_PORT": "443"}, False),
]


@pytest.mark.parametrize("shared_host,product_host,ports,same", HOST_RULE)
def test_setup_helper_and_server_agree_on_the_same_console(monkeypatch, shared_host, product_host, ports, same) -> None:
    import logging
    import os

    from unifi_mcp_shared import bootstrap

    legacy = {"UNIFI_PROTECT_HOST": product_host, **ports}
    if shared_host:
        legacy["UNIFI_HOST"] = shared_host
    for name in [n for n in os.environ if n.startswith("UNIFI_")]:
        monkeypatch.delenv(name)
    monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", None)
    for name, value in legacy.items():
        monkeypatch.setenv(name, value)
    cut, _ = bootstrap._host_level_cut(("host", "password"), (), env_prefix="PROTECT", logger=logging.getLogger("test"))
    assert (not cut) is same
    assert load_setup_config("protect").same_console(legacy, "PROTECT") is same


@pytest.mark.parametrize("target", ["codex", "openclaw"])
def test_original_shared_key_shadow_case_preserves_differing_saved_settings(tmp_path, monkeypatch, target) -> None:
    """Retain the original conflict input alongside the new matched shadow-entry fixtures."""
    import json
    from types import SimpleNamespace

    module = load_setup_config("sitemanager")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    config = tmp_path / "openclaw.json"
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config))
    if target == "codex":
        config = tmp_path / "codex/config.toml"
        config.parent.mkdir()
        config.write_text(
            '[mcp_servers."unifi-sitemanager"]\ncommand="fixture"\n'
            '[mcp_servers."unifi-sitemanager".env]\nUNIFI_API_KEY="FAKE-console"\n'
        )
        client = module.CodexClient()
    else:
        config.write_text(
            json.dumps(
                {
                    "mcp": {
                        "servers": {
                            "unifi-sitemanager": {"command": "fixture", "env": {"UNIFI_API_KEY": "FAKE-console"}}
                        }
                    }
                }
            )
        )
        client = module.OpenClawClient()
    settings = module.settings_path("SITEMANAGER")
    settings.parent.mkdir(parents=True)
    module.write_private(
        settings,
        module.settings_text({"UNIFI_SITEMANAGER_API_KEY_COMMAND": "fixture-provider"}, "unifi-sitemanager").encode(),
    )
    original = config.read_bytes(), settings.read_bytes()
    with pytest.raises(module.SetupError, match="A client entry shadows the bundled Site Manager server"):
        module.bundled_main(
            SimpleNamespace(check=False, refresh=False, dry_run=False),
            PLUGINS / "unifi-sitemanager",
            "unifi-sitemanager",
            "SITEMANAGER",
            {"UNIFI_SITEMANAGER_API_KEY": 'FAKE-cloud-only "quoted" Ω'},
            client,
        )
    assert (config.read_bytes(), settings.read_bytes()) == original


DRIVE_PASSWORD = "UNIFI_DRIVE_PASSWORD"


@pytest.mark.parametrize(
    "key",
    [
        "UNIFI_HOST",
        "UNIFI_PORT",
        "UNIFI_USERNAME",
        "UNIFI_SITE",
        "UNIFI_SSL_FINGERPRINT",
        "UNIFI_PASSWORD",
        "UNIFI_PASSWORD_FILE",
        "UNIFI_PASSWORD_COMMAND",
        "UNIFI_API_KEY",
        "UNIFI_API_KEY_FILE",
        "UNIFI_API_KEY_COMMAND",
        "UNIFI_DRIVE_API_KEY",
        "UNIFI_DRIVE_API_KEY_FILE",
        "UNIFI_DRIVE_API_KEY_COMMAND",
    ],
)
def test_drive_setup_refuses_shared_console_settings_and_api_keys(key: str) -> None:
    # The NAS is its own console: the server never reads these, so setup never saves them.
    module = load_setup_config("drive")
    for value in ("FAKE-input", "", None):
        with pytest.raises(module.SetupError, match="UniFi Drive reads only its own"):
            module.merge_env({}, {key: value}, "DRIVE", inherited={})
    with pytest.raises(module.SetupError, match="UniFi Drive reads only its own"):
        module.merge_env({key: "FAKE-existing"}, {}, "DRIVE", inherited={})


def test_drive_setup_saves_its_own_connection_policy_and_process_settings(tmp_path) -> None:
    module = load_setup_config("drive")
    password = tmp_path / "password"
    password.write_text("FAKE-password", encoding="utf-8")
    patch = {
        "UNIFI_DRIVE_HOST": "192.0.2.20",
        "UNIFI_DRIVE_USERNAME": "mcp",
        "UNIFI_DRIVE_PASSWORD_FILE": str(password),
        "UNIFI_DRIVE_PORT": "443",
        "UNIFI_DRIVE_VERIFY_SSL": "false",
        "UNIFI_DRIVE_SSL_FINGERPRINT": "AA:BB",
        "UNIFI_DRIVE_TOOL_PERMISSION_MODE": "confirm",
        "UNIFI_POLICY_DRIVE_UPDATE": "false",
        "UNIFI_POLICY_DRIVE_NFS_CONNECTIONS_DELETE": "true",
        "UNIFI_TOOL_REGISTRATION_MODE": "lazy",
    }
    assert module.merge_env({}, patch, "DRIVE", inherited={}) == patch


@pytest.mark.parametrize("suffixes", [("", "_FILE"), ("", "_COMMAND"), ("_FILE", "_COMMAND")])
def test_drive_setup_refuses_two_password_forms(tmp_path, suffixes) -> None:
    import sys

    module = load_setup_config("drive")
    path = tmp_path / "password"
    path.write_text("FAKE-password", encoding="utf-8")
    values = {"": "FAKE-password", "_FILE": str(path), "_COMMAND": sys.executable}
    patch = {DRIVE_PASSWORD + suffix: values[suffix] for suffix in suffixes}
    with pytest.raises(module.SetupError):
        module.merge_env({}, patch, "DRIVE", inherited={})
    with pytest.raises(module.SetupError):
        module.merge_env({}, {}, "DRIVE", inherited=patch)


def test_drive_password_switch_replaces_siblings_and_ignores_shared_providers(tmp_path) -> None:
    module = load_setup_config("drive")
    path = tmp_path / "password"
    path.write_text("FAKE-password", encoding="utf-8")
    # The server never falls back to the shared password, so a conflicting shared pair cannot stop it.
    shared = {"UNIFI_PASSWORD": "FAKE-shared", "UNIFI_PASSWORD_FILE": str(tmp_path / "missing")}
    assert module.merge_env(
        {DRIVE_PASSWORD: "FAKE-old"}, {DRIVE_PASSWORD + "_FILE": str(path)}, "DRIVE", inherited=shared
    ) == {DRIVE_PASSWORD + "_FILE": str(path)}


def test_drive_has_nothing_to_migrate() -> None:
    module = load_setup_config("drive")
    mapping = {"UNIFI_DRIVE_HOST": "host", "UNIFI_DRIVE_USERNAME": "username"}
    with pytest.raises(module.SetupError, match="UniFi Drive has no settings from an earlier plugin version"):
        module.legacy_patch({"UNIFI_DRIVE_HOST": "192.0.2.20"}, {"UNIFI_HOST": "192.0.2.1"}, mapping, "DRIVE")


@pytest.mark.parametrize("product", ["NETWORK", "PROTECT", "ACCESS"])
def test_console_legacy_settings_classify_drive_settings_as_another_product(tmp_path, monkeypatch, product) -> None:
    import json

    module = load_setup_config(product.lower())
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    env = {
        f"UNIFI_{product}_HOST": "192.0.2.1",
        "UNIFI_DRIVE_HOST": "192.0.2.20",
        "UNIFI_DRIVE_PASSWORD_FILE": "FAKE-drive-provider",
        "UNIFI_POLICY_DRIVE_UPDATE": "true",
        "UNIFI_HOST": "192.0.2.1",
    }
    (tmp_path / ".claude/settings.local.json").write_text(json.dumps({"env": env}))
    _, _, owned, shared = module.legacy_settings(product)
    assert owned == {f"UNIFI_{product}_HOST": "192.0.2.1"}
    assert shared == {"UNIFI_HOST": "192.0.2.1"}
    assert {"UNIFI_DRIVE_", "UNIFI_POLICY_DRIVE_"} <= set(module.other_prefixes(product))


@pytest.mark.parametrize("target", ["codex", "openclaw"])
def test_drive_refuses_a_shadowing_client_entry(tmp_path, monkeypatch, target) -> None:
    import json
    from types import SimpleNamespace

    module = load_setup_config("drive")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    config = tmp_path / "openclaw.json"
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config))
    if target == "codex":
        config = tmp_path / "codex/config.toml"
        config.parent.mkdir()
        config.write_text(
            '[mcp_servers."unifi-drive"]\ncommand="fixture"\n'
            '[mcp_servers."unifi-drive".env]\nUNIFI_DRIVE_HOST="192.0.2.20"\n'
        )
        client = module.CodexClient()
    else:
        entry = {"command": "fixture", "env": {"UNIFI_DRIVE_HOST": "192.0.2.20"}}
        config.write_text(json.dumps({"mcp": {"servers": {"unifi-drive": entry}}}))
        client = module.OpenClawClient()
    original = config.read_bytes()
    with pytest.raises(module.SetupError, match="A client entry shadows the bundled UniFi Drive server"):
        module.bundled_main(
            SimpleNamespace(check=False, refresh=False, dry_run=False),
            PLUGINS / "unifi-drive",
            "unifi-drive",
            "DRIVE",
            {"UNIFI_DRIVE_USERNAME": "mcp"},
            client,
        )
    assert config.read_bytes() == original
    assert not module.settings_path("DRIVE").exists()


# InnerSpace uses the console login session only. Setup never writes or checks the shared
# UNIFI_* keys (the server still falls back to them key by key) and never accepts an API key;
# the console helpers keep its keys apart.
INNERSPACE_PASSWORD = "UNIFI_INNERSPACE_PASSWORD"
INNERSPACE_API_KEY = "UNIFI_INNERSPACE_API_KEY"
SHARED_PASSWORD = "UNIFI_PASSWORD"
SHARED_API_KEY = "UNIFI_API_KEY"
INNERSPACE_ACCEPTED = {
    "UNIFI_INNERSPACE_HOST": "192.0.2.10",
    "UNIFI_INNERSPACE_USERNAME": "fixture-user",
    "UNIFI_INNERSPACE_PORT": "443",
    "UNIFI_INNERSPACE_VERIFY_SSL": "false",
    "UNIFI_INNERSPACE_SSL_FINGERPRINT": "AA:BB",
    "UNIFI_TOOL_REGISTRATION_MODE": "lazy",
}


def test_innerspace_setup_accepts_its_console_session_settings(tmp_path) -> None:
    module = load_setup_config("network")
    path = tmp_path / "password"
    path.write_text("FAKE-password")
    for key, value in ((INNERSPACE_PASSWORD, "FAKE-password"), (INNERSPACE_PASSWORD + "_FILE", str(path))):
        patch = {**INNERSPACE_ACCEPTED, key: value}
        assert module.merge_env({}, patch, "INNERSPACE", inherited={}) == patch


@pytest.mark.parametrize(
    "key",
    [
        "UNIFI_INNERSPACE_" + suffix
        for suffix in (
            "API_KEY",
            "API_KEY_FILE",
            "API_KEY_COMMAND",
            "SITE",
            "API_SSL_FINGERPRINT",
            "USERNAME_FILE",
            "PASSWORD_EXEC",
        )
    ]
    + [
        SHARED_API_KEY,
        SHARED_API_KEY + "_FILE",
        SHARED_API_KEY + "_COMMAND",
        "UNIFI_HOST",
        "UNIFI_USERNAME",
        SHARED_PASSWORD,
        SHARED_PASSWORD + "_FILE",
        SHARED_PASSWORD + "_COMMAND",
        "UNIFI_SETTINGS_FILE",
        "UNIFI_AUTO_CONFIRM",
        "UNIFI_ACCESS_HOST",
        "UNIFI_NETWORK_PASSWORD",
        "UNIFI_SITEMANAGER_API_KEY",
        "UNIFI_POLICY_INNERSPACE_WALL_TYPES_DELETE",
        "UNIFI_POLICY_INNERSPACE_PROJECT_CREATE",
        "UNIFI_POLICY_INNERSPACE_FLOOR_PLAN_UPDATE",
        "UNIFI_INNERSPACE_MCP_HTTP_ENABLED",
        "UNIFI_INNERSPACE_MCP_HTTP_AUTH_TOKEN",
        "UNIFI_INNERSPACE_MCP_HTTP_AUTH_TRUSTED_NETWORKS",
        "UNIFI_INNERSPACE_REDACT_SENSITIVE_FIELDS",
        "UNIFI_DRIVE_HOST",
        "UNIFI_POLICY_DRIVE_UPDATE",
        "UNIFI_POLICY_CREATE",
        "UNIFI_TOOL_PERMISSION_MODE",
        "UNIFI_READ_ONLY",
    ],
)
def test_innerspace_setup_rejects_other_settings_even_when_deleting(key: str) -> None:
    module = load_setup_config("network")
    for value in ("FAKE-input", "", None):
        with pytest.raises(module.SetupError):
            module.merge_env({}, {key: value}, "INNERSPACE", inherited={})
    with pytest.raises(module.SetupError):
        module.merge_env({key: "FAKE-existing"}, {}, "INNERSPACE", inherited={})


INNERSPACE_WRITE_SETTINGS = {
    "UNIFI_POLICY_INNERSPACE_CREATE": "false",
    "UNIFI_POLICY_INNERSPACE_UPDATE": "true",
    "UNIFI_POLICY_INNERSPACE_DELETE": "False",
    "UNIFI_INNERSPACE_TOOL_PERMISSION_MODE": "confirm",
    "UNIFI_INNERSPACE_READ_ONLY": "true",
    "UNIFI_INNERSPACE_REQUIRE_PREVIEW_TOKEN": "TRUE",
}


def test_innerspace_setup_accepts_the_write_gates_and_switches() -> None:
    module = load_setup_config("network")
    assert module.merge_env({}, INNERSPACE_WRITE_SETTINGS, "INNERSPACE", inherited={}) == INNERSPACE_WRITE_SETTINGS
    # A read-only switch added by hand no longer makes a later setup run refuse the file.
    saved = {"UNIFI_INNERSPACE_HOST": "192.0.2.10", "UNIFI_INNERSPACE_READ_ONLY": "true"}
    patch = {"UNIFI_INNERSPACE_USERNAME": "fixture-user", "UNIFI_INNERSPACE_REQUIRE_PREVIEW_TOKEN": None}
    assert module.merge_env(saved, patch, "INNERSPACE", inherited={}) == {
        **saved,
        "UNIFI_INNERSPACE_USERNAME": "fixture-user",
    }


# The server's category gates (permissions.md) and its operation-gate and content tuning.
INNERSPACE_CATEGORY_GATES = [
    "UNIFI_POLICY_INNERSPACE_" + gate
    for gate in (
        "WALLS_CREATE",
        "WALLS_UPDATE",
        "WALLS_DELETE",
        "WALL_TYPES_CREATE",
        "WALL_TYPES_UPDATE",
        "ATTENUATION_CREATE",
        "ATTENUATION_UPDATE",
        "ATTENUATION_DELETE",
        "FLOOR_PLANS_UPDATE",
        "FLOOR_PLANS_DELETE",
        "PROJECT_UPDATE",
    )
]
INNERSPACE_TUNING = {
    "UNIFI_INNERSPACE_WRITE_HOLD_SECONDS": "300",
    "UNIFI_INNERSPACE_CALL_WAIT_SECONDS": "2.5",
    "UNIFI_INNERSPACE_READ_CONCURRENCY": "4",
    "UNIFI_INNERSPACE_MCP_CONTENT_MODE": "compact",
}


def test_innerspace_setup_accepts_category_gates_and_tuning() -> None:
    module = load_setup_config("network")
    patch = {key: ("true" if index % 2 else "false") for index, key in enumerate(INNERSPACE_CATEGORY_GATES)}
    patch.update(INNERSPACE_TUNING)
    assert module.merge_env({}, patch, "INNERSPACE", inherited={}) == patch
    # Saved by hand in the settings file, they never make a later setup run refuse it.
    assert module.merge_env(patch, {"UNIFI_INNERSPACE_USERNAME": "fixture-user"}, "INNERSPACE", inherited={}) == {
        **patch,
        "UNIFI_INNERSPACE_USERNAME": "fixture-user",
    }


@pytest.mark.parametrize(
    "key, value",
    [
        ("UNIFI_POLICY_INNERSPACE_WALLS_DELETE", "yes"),
        ("UNIFI_INNERSPACE_WRITE_HOLD_SECONDS", "5"),
        ("UNIFI_INNERSPACE_WRITE_HOLD_SECONDS", "3601"),
        ("UNIFI_INNERSPACE_WRITE_HOLD_SECONDS", "two minutes"),
        ("UNIFI_INNERSPACE_CALL_WAIT_SECONDS", "0"),
        ("UNIFI_INNERSPACE_CALL_WAIT_SECONDS", "nan"),
        ("UNIFI_INNERSPACE_READ_CONCURRENCY", "65"),
        ("UNIFI_INNERSPACE_READ_CONCURRENCY", "1.5"),
        ("UNIFI_INNERSPACE_READ_CONCURRENCY", "\u00b2"),
        ("UNIFI_INNERSPACE_MCP_CONTENT_MODE", "json"),
    ],
)
def test_innerspace_setup_refuses_values_the_server_would_refuse(key: str, value: str) -> None:
    module = load_setup_config("network")
    with pytest.raises(module.SetupError, match=key):
        module.merge_env({}, {key: value}, "INNERSPACE", inherited={})


@pytest.mark.parametrize(
    "key", ["UNIFI_INNERSPACE_MCP_HTTP_AUTH_TOKEN", "UNIFI_INNERSPACE_REDACT_SENSITIVE_FIELDS", "UNIFI_DRIVE_HOST"]
)
def test_innerspace_refusal_names_the_key_but_never_its_value(key: str) -> None:
    module = load_setup_config("network")
    for saved, patch in (({}, {key: "FAKE-SENTINEL-value"}), ({key: "FAKE-SENTINEL-value"}, {})):
        with pytest.raises(module.SetupError) as refused:
            module.merge_env(saved, patch, "INNERSPACE", inherited={})
        assert key in str(refused.value) and "FAKE-SENTINEL" not in str(refused.value)


@pytest.mark.parametrize("value", ["confirm", "bypass", "BYPASS", " bypass "])
def test_innerspace_setup_accepts_confirm_and_bypass(value: str) -> None:
    module = load_setup_config("network")
    key = "UNIFI_INNERSPACE_TOOL_PERMISSION_MODE"
    assert module.merge_env({}, {key: value}, "INNERSPACE", inherited={}) == {key: value}
    assert module.merge_env({key: value}, {}, "INNERSPACE", inherited={}) == {key: value}


@pytest.mark.parametrize("value", ["auto", "yes", "confirm-all"])
def test_innerspace_setup_refuses_an_unknown_permission_mode(value: str) -> None:
    module = load_setup_config("network")
    key = "UNIFI_INNERSPACE_TOOL_PERMISSION_MODE"
    with pytest.raises(module.SetupError, match="confirm or bypass"):
        module.merge_env({}, {key: value}, "INNERSPACE", inherited={})
    with pytest.raises(module.SetupError, match="confirm or bypass"):
        module.merge_env({key: value}, {}, "INNERSPACE", inherited={})


@pytest.mark.parametrize("key", sorted(INNERSPACE_WRITE_SETTINGS.keys() - {"UNIFI_INNERSPACE_TOOL_PERMISSION_MODE"}))
@pytest.mark.parametrize("value", ["yes", "1", "on", "maybe"])
def test_innerspace_setup_takes_true_or_false_for_each_switch(key: str, value: str) -> None:
    module = load_setup_config("network")
    with pytest.raises(module.SetupError, match="take true or false"):
        module.merge_env({}, {key: value}, "INNERSPACE", inherited={})


def test_auto_confirm_notice_suggests_the_innerspace_bypass_mode() -> None:
    module = load_setup_config("network")
    notice = module.auto_confirm_notice({"UNIFI_AUTO_CONFIRM": "true"}, "INNERSPACE")
    assert "UNIFI_INNERSPACE_TOOL_PERMISSION_MODE=bypass" in notice
    assert "UNIFI_AUTO_CONFIRM" in notice and "FAKE" not in notice
    assert notice == module.auto_confirm_notice({"UNIFI_AUTO_CONFIRM": "true"}, "ACCESS").replace(
        "ACCESS", "INNERSPACE"
    )


@pytest.mark.parametrize("key", [INNERSPACE_API_KEY, INNERSPACE_API_KEY + "_FILE", SHARED_API_KEY])
def test_innerspace_setup_names_the_api_key_refusal(key: str) -> None:
    module = load_setup_config("network")
    with pytest.raises(module.SetupError, match="InnerSpace uses the console login only, never an API key"):
        module.merge_env({}, {key: "FAKE-console"}, "INNERSPACE", inherited={})


@pytest.mark.parametrize("suffixes", [("", "_FILE"), ("", "_COMMAND"), ("_FILE", "_COMMAND")])
def test_innerspace_setup_refuses_each_ambiguous_password_pair(tmp_path, suffixes) -> None:
    import sys

    module = load_setup_config("network")
    path = tmp_path / "password"
    path.write_text("FAKE-password")
    values = {"": "FAKE-password", "_FILE": str(path), "_COMMAND": sys.executable}
    patch = {INNERSPACE_PASSWORD + suffix: values[suffix] for suffix in suffixes}
    with pytest.raises(module.SetupError):
        module.merge_env({}, patch, "INNERSPACE", inherited={})
    with pytest.raises(module.SetupError):
        module.merge_env({}, {}, "INNERSPACE", inherited=patch)


def test_innerspace_setup_ignores_shared_credentials_and_switches_only_its_own_source(tmp_path) -> None:
    module = load_setup_config("network")
    path = tmp_path / "password"
    path.write_text("FAKE-password")
    # A console product validates these shared providers; InnerSpace never consults them.
    shared = dict(
        zip(
            (SHARED_PASSWORD, SHARED_PASSWORD + "_COMMAND", "UNIFI_HOST", SHARED_API_KEY + "_COMMAND"),
            ("FAKE-shared", "missing-shared-provider", "192.0.2.99", "missing-console-provider"),
        )
    )
    with pytest.raises(module.SetupError):
        module.merge_env({}, {}, "ACCESS", inherited=shared)
    assert module.merge_env({}, {}, "INNERSPACE", inherited=shared) == {}
    saved = {INNERSPACE_PASSWORD: "FAKE-old", "UNIFI_INNERSPACE_HOST": "192.0.2.10"}
    assert module.merge_env(saved, {INNERSPACE_PASSWORD + "_FILE": str(path)}, "INNERSPACE", inherited=shared) == {
        "UNIFI_INNERSPACE_HOST": "192.0.2.10",
        INNERSPACE_PASSWORD + "_FILE": str(path),
    }


@pytest.mark.parametrize(
    "suffix,value", [("_FILE", "relative-password"), ("_FILE", "/missing-password"), ("_COMMAND", "missing-provider")]
)
def test_innerspace_setup_validates_provider_references(suffix, value) -> None:
    module = load_setup_config("network")
    with pytest.raises(module.SetupError):
        module.merge_env({}, {INNERSPACE_PASSWORD + suffix: value}, "INNERSPACE", inherited={})


def test_innerspace_provider_validation_never_reads_or_executes_the_password(tmp_path, monkeypatch) -> None:
    import sys

    module = load_setup_config("network")
    path = tmp_path / "password"
    path.write_text("FAKE-provider-secret")

    def forbidden(*args, **kwargs):
        pytest.fail("Setup read or executed a credential provider")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(module.subprocess, "run", forbidden)
    for key, value in ((INNERSPACE_PASSWORD + "_FILE", str(path)), (INNERSPACE_PASSWORD + "_COMMAND", sys.executable)):
        assert module.merge_env({}, {key: value}, "INNERSPACE", inherited={}) == {key: value}


def test_innerspace_has_no_legacy_settings_to_migrate() -> None:
    module = load_setup_config("network")
    mapping = {"UNIFI_INNERSPACE_HOST": "host", INNERSPACE_PASSWORD: "password"}
    with pytest.raises(module.SetupError, match="InnerSpace has no legacy settings to migrate"):
        module.legacy_patch(
            {"UNIFI_INNERSPACE_HOST": "192.0.2.10"}, {SHARED_PASSWORD: "FAKE-shared"}, mapping, "INNERSPACE"
        )


@pytest.mark.parametrize("product", ["NETWORK", "PROTECT", "ACCESS", "SITEMANAGER", "DRIVE"])
def test_sibling_helpers_keep_innerspace_keys_separate(tmp_path, monkeypatch, product) -> None:
    import json

    module = load_setup_config(product.lower())
    others = module.other_prefixes(product)
    assert "UNIFI_INNERSPACE_" in others and "UNIFI_POLICY_INNERSPACE_" in others
    assert f"UNIFI_{product}_" in module.other_prefixes("INNERSPACE")
    if product in ("SITEMANAGER", "DRIVE"):
        return
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    env = {
        f"UNIFI_{product}_HOST": "192.0.2.1",
        "UNIFI_INNERSPACE_HOST": "192.0.2.20",
        INNERSPACE_PASSWORD + "_FILE": "FAKE-innerspace-provider",
        "UNIFI_POLICY_INNERSPACE_WALLS_DELETE": "false",
        SHARED_API_KEY: "FAKE-shared-console",
    }
    (tmp_path / ".claude/settings.local.json").write_text(json.dumps({"env": env}))
    _, _, owned, shared = module.legacy_settings(product)
    assert owned == {f"UNIFI_{product}_HOST": "192.0.2.1"}
    assert shared == {SHARED_API_KEY: "FAKE-shared-console"}


@pytest.mark.parametrize("product", ["network", "protect", "access"])
def test_console_helpers_save_innerspace_named_inputs_unchanged(tmp_path, product) -> None:
    # The helper released before the InnerSpace mode accepted these inputs for a
    # console product and saved them unchanged; it still does.
    patch = {
        "UNIFI_INNERSPACE_HOST": "192.0.2.20",
        INNERSPACE_PASSWORD + "_FILE": str(tmp_path / "missing-provider"),
        INNERSPACE_API_KEY: "FAKE-opaque",
    }
    module = load_setup_config(product)
    assert module.merge_env({}, dict(patch), product.upper(), inherited={}) == patch


def test_innerspace_package_pin_is_recognised(tmp_path) -> None:
    import json

    module = load_setup_config("network")
    (tmp_path / ".claude-plugin").mkdir()
    server = {"command": "uvx", "args": ["--python-preference", "system", "unifi-innerspace-mcp==0.1.0"]}
    (tmp_path / ".claude-plugin/plugin.json").write_text(json.dumps({"mcpServers": {"unifi-innerspace": server}}))
    (tmp_path / ".mcp.codex.json").write_text(json.dumps({"mcpServers": {"unifi-innerspace": server}}))
    assert module.package_pin(tmp_path, "unifi-innerspace", bundled=True) == "unifi-innerspace-mcp==0.1.0"


def _innerspace_openclaw(module, tmp_path, monkeypatch, entry=None):
    import json

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = tmp_path / "openclaw.json"
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config))
    servers = {"unifi-innerspace": entry} if entry is not None else {}
    config.write_text(json.dumps({"mcp": {"servers": servers}}))
    return config, module.OpenClawClient()


def test_innerspace_settings_file_is_private_and_setup_prints_no_value(tmp_path, monkeypatch, capsys) -> None:
    import os
    from types import SimpleNamespace

    module = load_setup_config("network")
    _, client = _innerspace_openclaw(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module.shutil, "which", lambda name, path=None: "/usr/bin/" + name)
    patch = {
        "UNIFI_INNERSPACE_HOST": "192.0.2.77",
        "UNIFI_INNERSPACE_USERNAME": "FAKE-innerspace-user",
        INNERSPACE_PASSWORD + "_COMMAND": "fixture-password-helper --vault FAKE-vault-item",
    }
    module.bundled_main(
        SimpleNamespace(check=False, refresh=False, dry_run=False),
        tmp_path / "plugin",
        "unifi-innerspace",
        "INNERSPACE",
        patch,
        client,
    )
    path = module.settings_path("INNERSPACE")
    assert path == tmp_path / ".config" / "unifi-mcp" / "innerspace.env"
    assert module.read_settings(path) == {**patch, **INNERSPACE_FIRST_SETUP_DEFAULTS}
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr()
    for value in (*patch.values(), "FAKE-vault-item"):
        assert value not in output.out + output.err


@pytest.mark.parametrize("credential", ["shared", "own", None])
def test_innerspace_refuses_a_shadowing_client_entry(tmp_path, monkeypatch, credential) -> None:
    from types import SimpleNamespace

    module = load_setup_config("network")
    entry = {"command": "fixture"}
    entry_env = None
    if credential is not None:
        entry_env = {(SHARED_PASSWORD if credential == "shared" else INNERSPACE_PASSWORD): "FAKE-shadow"}
        entry["env"] = entry_env
    config, client = _innerspace_openclaw(module, tmp_path, monkeypatch, entry)
    settings = module.settings_path("INNERSPACE")
    settings.parent.mkdir(parents=True)
    # Matching file and entry settings, so the conflict check cannot stand in for the refusal.
    module.write_private(settings, module.settings_text(entry_env or {}, "unifi-innerspace").encode())
    original = config.read_bytes(), settings.read_bytes()
    with pytest.raises(module.SetupError, match="A client entry shadows the bundled InnerSpace server"):
        module.bundled_main(
            SimpleNamespace(check=False, refresh=False, dry_run=False),
            tmp_path / "plugin",
            "unifi-innerspace",
            "INNERSPACE",
            {INNERSPACE_PASSWORD: "FAKE-password"},
            client,
        )
    assert (config.read_bytes(), settings.read_bytes()) == original


# Writes stay off on Codex and OpenClaw until the user opts in, as the Claude Code options default.
INNERSPACE_FIRST_SETUP_DEFAULTS = {
    "UNIFI_POLICY_INNERSPACE_CREATE": "false",
    "UNIFI_POLICY_INNERSPACE_UPDATE": "false",
    "UNIFI_POLICY_INNERSPACE_DELETE": "false",
    "UNIFI_INNERSPACE_TOOL_PERMISSION_MODE": "confirm",
}


def _innerspace_setup(module, client, patch) -> dict:
    from types import SimpleNamespace

    module.bundled_main(
        SimpleNamespace(check=False, refresh=False, dry_run=False),
        Path("/nonexistent/plugin"),
        "unifi-innerspace",
        "INNERSPACE",
        patch,
        client,
    )
    return module.read_settings(module.settings_path("INNERSPACE"))


def test_innerspace_first_bundled_setup_saves_writes_off(tmp_path, monkeypatch) -> None:
    module = load_setup_config("network")
    _, client = _innerspace_openclaw(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module.shutil, "which", lambda name, path=None: "/usr/bin/" + name)
    login = {"UNIFI_INNERSPACE_HOST": "192.0.2.10", "UNIFI_INNERSPACE_USERNAME": "fixture-user"}
    saved = _innerspace_setup(module, client, login)
    assert saved == {**login, **INNERSPACE_FIRST_SETUP_DEFAULTS}
    # The saved file is what the server reads: no write is allowed and confirmation stays on.
    assert {saved[key] for key in INNERSPACE_FIRST_SETUP_DEFAULTS} == {"false", "confirm"}
    # A later run keeps the user's own changes, including a gate they removed.
    later = _innerspace_setup(
        module, client, {"UNIFI_POLICY_INNERSPACE_UPDATE": "true", "UNIFI_POLICY_INNERSPACE_DELETE": None}
    )
    assert later["UNIFI_POLICY_INNERSPACE_UPDATE"] == "true"
    assert "UNIFI_POLICY_INNERSPACE_DELETE" not in later


def test_innerspace_first_bundled_setup_keeps_explicit_write_choices(tmp_path, monkeypatch) -> None:
    module = load_setup_config("network")
    _, client = _innerspace_openclaw(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module.shutil, "which", lambda name, path=None: "/usr/bin/" + name)
    patch = {
        "UNIFI_INNERSPACE_HOST": "192.0.2.10",
        "UNIFI_POLICY_INNERSPACE_UPDATE": "true",
        "UNIFI_INNERSPACE_TOOL_PERMISSION_MODE": "bypass",
    }
    saved = _innerspace_setup(module, client, patch)
    assert saved["UNIFI_POLICY_INNERSPACE_UPDATE"] == "true"
    assert saved["UNIFI_INNERSPACE_TOOL_PERMISSION_MODE"] == "bypass"
    assert saved["UNIFI_POLICY_INNERSPACE_CREATE"] == saved["UNIFI_POLICY_INNERSPACE_DELETE"] == "false"


@pytest.mark.parametrize("product", ["network", "drive"])
def test_other_bundled_setups_add_no_write_defaults(tmp_path, monkeypatch, product) -> None:
    module = load_setup_config(product)
    assert module.first_setup_defaults(product.upper()) == {}
    assert module.first_setup_defaults("INNERSPACE") == INNERSPACE_FIRST_SETUP_DEFAULTS
