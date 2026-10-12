"""Pytest configuration for the repository-level tests."""

import sys
from pathlib import Path

# Scrub inherited controller settings and block outbound network access before
# anything imports code under test; see testsupport/unifi_test_guard.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "testsupport"))
import unifi_test_guard  # noqa: E402

unifi_test_guard.protect_test_session()

from unifi_test_guard import fail_on_outbound_network_access, pytest_configure  # noqa: E402,F401
