"""Pytest configuration for unifi-network-mcp tests."""

import sys
from pathlib import Path

# Scrub inherited controller settings and block outbound network access before
# anything imports the code under test; see testsupport/unifi_test_guard.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "testsupport"))
import unifi_test_guard  # noqa: E402

unifi_test_guard.protect_test_session()

from unifi_test_guard import fail_on_outbound_network_access, pytest_configure  # noqa: E402,F401

stub_automatic_controller_connects = unifi_test_guard.connect_stub("unifi_network_mcp.runtime")

# Add the network app's src directory to path so unifi_network_mcp is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
