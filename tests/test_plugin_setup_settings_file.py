"""The Codex settings file that setup writes reads back exactly under the server's dotenv rules."""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
PRODUCTS = ("network", "protect", "access", "sitemanager")
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


def test_the_four_plugin_copies_are_identical() -> None:
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
def test_console_cloud_named_inputs_match_pre_bundle_helper(tmp_path, product, case) -> None:
    import copy
    import subprocess
    import types

    # Fixed pre-bundle revision: HEAD~2 when the independent review was requested.
    root = PLUGINS.parent
    source = subprocess.run(
        ["git", "show", f"47deaedf:plugins/unifi-{product}/scripts/setup_config.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    baseline = types.ModuleType("pre_bundle_setup")
    exec(compile(source, "pre-bundle-setup", "exec"), baseline.__dict__)
    missing = str(tmp_path / "missing-provider")
    patch = {
        "missing_file": {"UNIFI_SITEMANAGER_API_KEY_FILE": missing},
        "unknown_suffix": {"UNIFI_SITEMANAGER_API_KEY_X": "FAKE-opaque"},
        "two_forms": {"UNIFI_SITEMANAGER_API_KEY": "FAKE-opaque", "UNIFI_SITEMANAGER_API_KEY_FILE": missing},
    }[case]
    expected = copy.deepcopy(patch)
    before = baseline.merge_env({}, patch, product.upper(), inherited={})
    assert before == expected
    module = load_setup_config(product)
    merged = module.merge_env({}, patch, product.upper(), inherited={})
    assert merged == before
    # Exercise publication, not just admission: the same opaque inputs still save.
    settings = tmp_path / "console-settings"
    module.write_private(settings, module.settings_text(merged, f"unifi-{product}").encode())
    assert module.read_settings(settings) == before


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
    assert patch == {f"UNIFI_{product}_HOST": "192.0.2.1", f"UNIFI_{product}_API_KEY": "FAKE-shared-console-key"}


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
