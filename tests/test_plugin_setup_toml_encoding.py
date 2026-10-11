"""The Codex config.toml editor writes TOML basic strings that tomllib reads back unchanged."""

from __future__ import annotations

import importlib.util
import random
import tomllib
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
PRODUCTS = ("network", "protect", "access")
NON_ASCII = "é中 \u0085 😀﻿\U0010ffff"


def load_setup_config(product: str):
    path = PLUGINS / f"unifi-{product}" / "scripts" / "setup_config.py"
    spec = importlib.util.spec_from_file_location(f"setup_config_{product}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def round_trip(module, value):
    document = tomllib.loads(f"value = {module.toml_value(value)}\n")
    return document["value"]


@pytest.mark.parametrize("product", PRODUCTS)
def test_every_control_character_round_trips_escaped(product: str) -> None:
    module = load_setup_config(product)
    for code in [*range(0x20), 0x7F]:
        char = chr(code)
        encoded = module.toml_value(f"a{char}b")
        assert char not in encoded, hex(code)
        assert round_trip(module, f"a{char}b") == f"a{char}b", hex(code)


@pytest.mark.parametrize("product", PRODUCTS)
def test_escaped_del_key_and_value_survive_in_an_inline_table(product: str) -> None:
    module = load_setup_config(product)
    source = {"KEEP": "synthetic", "\x7f": "synthetic", "k\x01\x1f": "v\x7f"}
    encoded = module.toml_value(source)
    assert "\x7f" not in encoded
    assert tomllib.loads(f"env = {encoded}\n")["env"] == source


@pytest.mark.parametrize("product", PRODUCTS)
def test_other_unicode_stays_raw(product: str) -> None:
    module = load_setup_config(product)
    encoded = module.toml_value(NON_ASCII)
    assert NON_ASCII in encoded
    assert round_trip(module, NON_ASCII) == NON_ASCII


@pytest.mark.parametrize("product", PRODUCTS)
def test_random_strings_round_trip(product: str) -> None:
    module = load_setup_config(product)
    rng = random.Random(20261011)
    alphabet = [chr(code) for code in range(0x20)] + ['"', "\\", "\x7f", "a", " ", "#", "[", "=", *NON_ASCII]
    for _ in range(2000):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))
        document = tomllib.loads(f"{module.toml_string(value)} = {module.toml_value(value)}\n")
        assert document == {value: value}
        encoded = module.toml_value(value)
        assert not any(ord(char) < 0x20 or ord(char) == 0x7F for char in encoded)


def test_the_three_plugin_copies_are_identical() -> None:
    copies = {(PLUGINS / f"unifi-{product}" / "scripts" / "setup_config.py").read_bytes() for product in PRODUCTS}
    assert len(copies) == 1
