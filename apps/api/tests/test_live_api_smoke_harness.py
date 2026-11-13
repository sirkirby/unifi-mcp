"""Self-tests for scripts/live_api_smoke.py."""

from __future__ import annotations

import io
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


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_smoke_closes_sessions_after_success_or_failure(tmp_path, monkeypatch, fail):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import live_api_smoke

    invalidate = AsyncMock()
    dispose = AsyncMock()
    app = SimpleNamespace(
        state=SimpleNamespace(
            manager_factory=SimpleNamespace(invalidate_controller=invalidate),
            engine=SimpleNamespace(dispose=dispose),
        )
    )
    bootstrap = AsyncMock(return_value=(app, "synthetic-key", {"network": "synthetic-controller"}))
    monkeypatch.setattr(live_api_smoke, "load_env", lambda: {})
    monkeypatch.setattr(live_api_smoke, "bootstrap_app_and_controllers", bootstrap)
    monkeypatch.setattr(
        live_api_smoke, "_run_assertion", AsyncMock(side_effect=RuntimeError("probe failed") if fail else None)
    )
    args = SimpleNamespace(controllers="", retry=1, installed=True, output=tmp_path / "report.json")
    if fail:
        with pytest.raises(RuntimeError, match="probe failed"):
            await live_api_smoke.main_async(args)
    else:
        assert await live_api_smoke.main_async(args) == 0
    bootstrap.assert_awaited_once_with({}, [], installed=True)
    invalidate.assert_awaited_once_with("synthetic-controller")
    dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_installed_smoke_does_not_add_checkout_to_import_path(monkeypatch):
    import live_api_smoke

    monkeypatch.setattr(sys, "path", sys.path.copy())
    before = sys.path.copy()
    app, _key, controllers = await live_api_smoke.bootstrap_app_and_controllers({}, [], installed=True)
    try:
        assert sys.path == before
        assert controllers == {}
    finally:
        await app.state.engine.dispose()


def test_api_image_catalog_validation_requires_exact_generated_names():
    import api_image_smoke

    expected = {"unifi_list_clients", "protect_list_cameras", "access_list_doors"}

    result = api_image_smoke._validate_catalog_response(
        {"items": [{"name": name} for name in sorted(expected)]},
        expected,
    )

    assert result == {"count": 3, "missing": [], "unexpected": []}


def test_api_image_catalog_validation_reports_drift():
    import api_image_smoke

    result = api_image_smoke._validate_catalog_response(
        {"items": [{"name": "unifi_list_clients"}, {"name": "obsolete_tool"}]},
        {"unifi_list_clients", "protect_list_cameras"},
    )

    assert result == {
        "count": 2,
        "missing": ["protect_list_cameras"],
        "unexpected": ["obsolete_tool"],
    }


def test_api_image_catalog_fetch_can_read_response_larger_than_default_limit(monkeypatch):
    import api_image_smoke

    body = b'{"items":[' + (b'{"name":"unifi_list_clients"},' * 300) + b'{"name":"last"}]}'

    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(api_image_smoke.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(body))

    status, fetched, _elapsed = api_image_smoke._hit("http://example.test/catalog", "key", max_bytes=None)

    assert status == 200
    assert fetched.encode() == body
    assert len(fetched) > 8192


def test_api_image_smoke_expects_only_the_unconfigured_cloud_account_503():
    import api_image_smoke

    unconfigured = '{"detail": {"kind": "sitemanager_not_configured", "message": "x"}}'
    assert "expected" in api_image_smoke._classify(503, unconfigured)
    assert api_image_smoke._classify(503, '{"detail": {"kind": "other"}}') == "503 server-error"
    assert api_image_smoke._classify(503, "not json") == "503 server-error"
