"""Self-tests for scripts/live_api_smoke.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))


def test_load_env_parses_a_synthetic_dotenv(tmp_path, monkeypatch):
    """load_env() parses comments, quoted values, and KEY=VALUE pairs.

    Uses a synthetic .env in tmp_path so this works in CI (where the real
    repo-root .env is absent) and locally (without depending on actual creds).
    """
    import live_api_smoke

    env_file = tmp_path / ".env"
    env_file.write_text("# a comment\n\nPLAIN=value1\nQUOTED=\"value with spaces\"\nSINGLE='single'\n")
    monkeypatch.setattr(live_api_smoke, "REPO_ROOT", tmp_path)

    env = live_api_smoke.load_env()
    assert env == {"PLAIN": "value1", "QUOTED": "value with spaces", "SINGLE": "single"}


def test_load_env_raises_when_dotenv_absent(tmp_path, monkeypatch):
    """load_env() raises SystemExit if .env is missing — preserves the existing contract."""
    import live_api_smoke

    monkeypatch.setattr(live_api_smoke, "REPO_ROOT", tmp_path)
    with pytest.raises(SystemExit, match=".env not found"):
        live_api_smoke.load_env()


def test_assertion_dataclass_serializes():
    from dataclasses import asdict

    from live_api_smoke import Assertion

    a = Assertion(name="x", product="network", surface="rest")
    d = asdict(a)
    assert d["name"] == "x"
    assert d["passed"] is False


def test_report_counters():
    from live_api_smoke import Assertion, Report

    r = Report()
    r.assertions.append(Assertion(name="ok", product="x", surface="rest", passed=True))
    r.assertions.append(Assertion(name="bad", product="x", surface="rest", passed=False))
    assert r.total == 2
    assert r.passed == 1
    assert r.failed == 1
