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
