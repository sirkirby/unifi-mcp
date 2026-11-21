"""InnerSpace test fixtures: the loopback console stub lives in testsupport/innerspace_stub.py.

The app's tests share it, so it is imported here by name for pytest to find the fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "testsupport"))

from innerspace_stub import (  # noqa: E402,F401
    ACCESS_DENIED,
    HOST,
    LOGIN,
    LOGOUT,
    PASSWORD,
    USERNAME,
    Recorded,
    StubConsole,
    connected,
    console,
    manager,
    start_stub,
)
