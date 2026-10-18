"""Run ``unittest discover`` behind the shared network guard.

unittest never loads a conftest, so unittest-style suites run through this
instead: ``python testsupport/run_unittest.py -s tests/docs -p 'test_*.py' -v``.
The run fails if any test attempted outbound network access, even when the
code under test swallowed the refusal.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unifi_test_guard  # noqa: E402


def main(argv: list[str]) -> int:
    unifi_test_guard.protect_test_session()
    program = unittest.main(module=None, argv=["unittest", "discover", *argv], exit=False)
    blocked = unifi_test_guard.blocked_network_access()
    if blocked:
        print(f"tests attempted outbound network access: {blocked}; use loopback stubs or mocks", file=sys.stderr)
        return 1
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
