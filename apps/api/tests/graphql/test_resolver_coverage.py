"""CI gate: every typed resolver in type_registry has a fixture e2e test.

Phase 8 PR2 invariant: prevents Phase 6's silent-coverage gap (PR #130
ACL pattern — controller had zero rules, mutation path went unsmoked)
from recurring at the resolver level.

Each entry in ``type_registry._tool_types`` must have a corresponding
fixture test that exercises the resolver. Fixture tests declare which
tools they cover via ``# tool: <name>`` comments at module top.
"""

from __future__ import annotations

from pathlib import Path

from unifi_api.graphql.type_registry_init import build_type_registry

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _scan_fixture_tools() -> set[str]:
    """Scan fixture test files for ``# tool: <name>`` declarations."""
    covered: set[str] = set()
    if not FIXTURE_DIR.exists():
        return covered
    for path in FIXTURE_DIR.rglob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# tool:"):
                covered.add(stripped.split("# tool:", 1)[1].strip())
    return covered


def test_every_typed_resolver_has_fixture_coverage() -> None:
    type_registry = build_type_registry()
    expected = set(type_registry._tool_types.keys())  # noqa: SLF001
    covered = _scan_fixture_tools()

    missing = expected - covered
    assert not missing, (
        f"Missing fixture coverage for {len(missing)} typed resolvers:\n"
        + "\n".join(f"  - {t}" for t in sorted(missing))
        + "\nAdd a `# tool: <name>` comment + matching test in apps/api/tests/graphql/fixtures/<product>/test_<file>.py"
    )
