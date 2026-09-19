"""Pytest configuration for unifi-api tests."""

import sys
from pathlib import Path

import pytest
from argon2 import PasswordHasher

# Add the api app's src directory to path so unifi_api is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(scope="session", autouse=True)
def fast_argon2_hasher():
    """Keep authentication semantics without paying production hash costs per test."""
    from unifi_api.auth import api_key

    production_hasher = api_key._HASHER
    api_key._HASHER = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    try:
        yield
    finally:
        api_key._HASHER = production_hasher
