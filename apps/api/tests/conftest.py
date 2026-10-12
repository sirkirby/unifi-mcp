"""Pytest configuration for unifi-api tests."""

import sys
from pathlib import Path

# Scrub inherited controller settings and block outbound network access before
# anything imports the code under test; see testsupport/unifi_test_guard.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "testsupport"))
import unifi_test_guard  # noqa: E402

unifi_test_guard.protect_test_session()

from unifi_test_guard import fail_on_outbound_network_access, pytest_configure  # noqa: E402,F401

stub_automatic_controller_connects = unifi_test_guard.connect_stub()

import pytest  # noqa: E402
from argon2 import PasswordHasher  # noqa: E402

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
