"""The Codex settings file that setup writes reads back exactly under the server's dotenv rules."""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
PRODUCTS = ("network", "protect", "access")
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


def test_the_three_plugin_copies_are_identical() -> None:
    copies = {(PLUGINS / f"unifi-{product}" / "scripts" / "setup_config.py").read_bytes() for product in PRODUCTS}
    assert len(copies) == 1
