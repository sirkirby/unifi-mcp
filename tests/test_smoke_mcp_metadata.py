"""Tests for the MCP metadata smoke script helpers."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

_script_path = Path(__file__).parent.parent / "scripts" / "smoke_mcp_metadata.py"
_spec = importlib.util.spec_from_file_location("smoke_mcp_metadata", _script_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

MetadataSmokeError = _mod.MetadataSmokeError
PROJECT_WEBSITE_URL = _mod.PROJECT_WEBSITE_URL
SERVER_SPECS = _mod.SERVER_SPECS
validate_icons = _mod.validate_icons
validate_server_metadata = _mod.validate_server_metadata
validate_meta_tool_surface = _mod.validate_meta_tool_surface
smoke_env = _mod.smoke_env
selected_server_names = _mod.selected_server_names
run_smoke_matrix = _mod.run_smoke_matrix

NETWORK_SPEC = SERVER_SPECS["network"]

EXPECTED_SURFACE = frozenset(
    {
        "MetadataSmokeError",
        "PROJECT_WEBSITE_URL",
        "SERVER_SPECS",
        "ServerSpec",
        "parse_meta_tool_result",
        "run_smoke_matrix",
        "selected_server_names",
        "smoke_env",
        "smoke_server",
        "validate_connection",
        "validate_icons",
        "validate_index_catalog",
        "validate_meta_tool_surface",
        "validate_mode_tools",
        "validate_server_metadata",
        "validate_tool_schema",
    }
)


def _meta_tools(spec, **overrides):
    """A tools/list payload that passes every check in validate_meta_tool_surface."""
    index_tool = SimpleNamespace(
        name=spec.index_tool,
        title=spec.expected_index_title,
        description="Index of available tools.",
        inputSchema={"type": "object"},
        annotations=SimpleNamespace(readOnlyHint=True, openWorldHint=False),
    )
    for key, value in overrides.items():
        setattr(index_tool, key, value)
    return [
        index_tool,
        SimpleNamespace(name=f"{spec.prefix}_execute"),
        SimpleNamespace(name=f"{spec.prefix}_batch"),
        SimpleNamespace(name=f"{spec.prefix}_batch_status"),
    ]


def test_module_public_surface_is_stable() -> None:
    """Name every helper the smoke script owes this file, so a rename reports all gaps at once."""
    assert EXPECTED_SURFACE <= set(vars(_mod)), sorted(EXPECTED_SURFACE - set(vars(_mod)))


PNG_DATA_URI = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()


def _icon(size: str = "48x48"):
    return SimpleNamespace(src=PNG_DATA_URI, mimeType="image/png", sizes=[size])


def _server_info(**overrides):
    """An initialize.serverInfo payload that passes every check."""
    fields = {
        "name": NETWORK_SPEC.expected_name,
        "websiteUrl": PROJECT_WEBSITE_URL,
        "version": "1.2.3",
        "icons": [_icon("48x48"), _icon("96x96"), _icon("192x192")],
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_validate_icons_accepts_three_png_data_uri_sizes() -> None:
    validate_icons([_icon("48x48"), _icon("96x96"), _icon("192x192")], label="test")


def test_validate_icons_rejects_non_png_data() -> None:
    icon = SimpleNamespace(
        src="data:image/png;base64," + base64.b64encode(b"not-png").decode(), mimeType="image/png", sizes=["48x48"]
    )

    with pytest.raises(MetadataSmokeError, match="not PNG data"):
        validate_icons([icon, _icon("96x96"), _icon("192x192")], label="test")


def test_validate_server_metadata_checks_name_website_and_icons() -> None:
    validate_server_metadata(NETWORK_SPEC, _server_info())


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("name", "unifi-wrong-mcp", "expected server name"),
        ("websiteUrl", "https://example.invalid/other", "expected websiteUrl"),
        ("version", "", "missing server version"),
    ],
)
def test_validate_server_metadata_rejects_each_bad_field(field, value, expected) -> None:
    with pytest.raises(MetadataSmokeError, match=expected):
        validate_server_metadata(NETWORK_SPEC, _server_info(**{field: value}))


def test_validate_meta_tool_surface_accepts_a_complete_lazy_surface() -> None:
    validate_meta_tool_surface(NETWORK_SPEC, _meta_tools(NETWORK_SPEC))


def test_validate_meta_tool_surface_requires_expected_index_title() -> None:
    tools = _meta_tools(NETWORK_SPEC, title="Wrong Title")

    with pytest.raises(MetadataSmokeError, match="expected title"):
        validate_meta_tool_surface(NETWORK_SPEC, tools)


def test_validate_meta_tool_surface_requires_every_meta_tool() -> None:
    tools = [tool for tool in _meta_tools(NETWORK_SPEC) if not tool.name.endswith("_batch_status")]

    with pytest.raises(MetadataSmokeError, match="missing meta-tools"):
        validate_meta_tool_surface(NETWORK_SPEC, tools)


def test_smoke_env_defaults_to_offline_metadata_credentials(monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_HOST", "10.0.0.1")
    monkeypatch.setenv("UNIFI_NETWORK_HOST", "10.0.0.2")
    monkeypatch.setenv("UNIFI_TOOL_REGISTRATION_MODE", "meta_only")
    monkeypatch.setenv("UNIFI_MCP_HTTP_ENABLED", "true")

    env = smoke_env(registration_mode="lazy", use_current_env=False)

    assert env["UNIFI_HOST"] == "127.0.0.1"
    assert env["UNIFI_NETWORK_HOST"] == "127.0.0.1"
    assert env["UNIFI_USERNAME"] == "metadata-smoke"
    assert env["UNIFI_TOOL_REGISTRATION_MODE"] == "lazy"
    assert env["UNIFI_MCP_HTTP_ENABLED"] == "false"


def test_smoke_env_can_preserve_current_controller_env(monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_HOST", "10.0.0.1")
    monkeypatch.setenv("UNIFI_TOOL_REGISTRATION_MODE", "meta_only")
    monkeypatch.setenv("UNIFI_MCP_HTTP_ENABLED", "true")

    env = smoke_env(registration_mode="eager", use_current_env=True)

    assert env["UNIFI_HOST"] == "10.0.0.1"
    assert env["UNIFI_TOOL_REGISTRATION_MODE"] == "eager"
    assert env["UNIFI_MCP_HTTP_ENABLED"] == "false"


def test_selected_server_names_skips_access_for_default_offline_smoke() -> None:
    assert selected_server_names(server="all", use_current_env=False) == ["network", "protect"]


def test_selected_server_names_includes_access_with_current_env() -> None:
    assert selected_server_names(server="all", use_current_env=True) == ["network", "protect", "access"]


def test_selected_server_names_rejects_access_without_current_env() -> None:
    with pytest.raises(MetadataSmokeError, match="requires --use-current-env"):
        selected_server_names(server="access", use_current_env=False)


def test_run_smoke_matrix_runs_cases_concurrently_and_preserves_order(monkeypatch) -> None:
    async def exercise() -> tuple[int, list[str]]:
        started = 0
        max_active = 0
        release = anyio.Event()

        async def fake_smoke_server(spec, *, registration_mode, client_mode, use_current_env=False):
            nonlocal started, max_active
            started += 1
            max_active = max(max_active, started)
            if started == 4:
                release.set()
            await release.wait()
            started -= 1
            return f"{spec.expected_name}:{registration_mode}:{client_mode}:{use_current_env}"

        monkeypatch.setattr(_mod, "smoke_server", fake_smoke_server)
        with anyio.fail_after(1):
            results = await run_smoke_matrix(
                ["network", "protect"],
                ["lazy"],
                ["auto", "legacy"],
                use_current_env=False,
            )
        return max_active, results

    max_active, results = anyio.run(exercise)

    assert max_active == 4
    assert results == [
        "unifi-network-mcp:lazy:auto:False",
        "unifi-network-mcp:lazy:legacy:False",
        "unifi-protect-mcp:lazy:auto:False",
        "unifi-protect-mcp:lazy:legacy:False",
    ]


def test_run_smoke_matrix_serializes_live_controller_cases(monkeypatch) -> None:
    async def exercise() -> tuple[int, list[str]]:
        active = 0
        max_active = 0

        async def fake_smoke_server(spec, *, registration_mode, client_mode, use_current_env=False):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await anyio.sleep(0)
            active -= 1
            return f"{spec.expected_name}:{registration_mode}:{client_mode}:{use_current_env}"

        monkeypatch.setattr(_mod, "smoke_server", fake_smoke_server)
        results = await run_smoke_matrix(
            ["network", "protect", "access"],
            ["lazy"],
            ["auto", "legacy"],
            use_current_env=True,
        )
        return max_active, results

    max_active, results = anyio.run(exercise)

    assert max_active == 1
    assert len(results) == 6


def test_run_smoke_matrix_identifies_failed_case_and_cancels_siblings(monkeypatch) -> None:
    async def exercise() -> None:
        sibling_started = anyio.Event()
        sibling_cancelled = anyio.Event()

        async def fake_smoke_server(spec, *, registration_mode, client_mode, use_current_env=False):
            if spec is NETWORK_SPEC:
                sibling_started.set()
                try:
                    await anyio.sleep_forever()
                finally:
                    sibling_cancelled.set()
            await sibling_started.wait()
            raise RuntimeError("boom")

        monkeypatch.setattr(_mod, "smoke_server", fake_smoke_server)
        with pytest.raises(ExceptionGroup) as exc_info:
            await run_smoke_matrix(
                ["network", "protect"],
                ["eager"],
                ["legacy"],
                use_current_env=False,
            )

        assert sibling_cancelled.is_set()
        assert any(
            "unifi-protect-mcp: metadata smoke failed for mode=eager client=legacy" in str(error)
            for error in exc_info.value.exceptions
        )

    anyio.run(exercise)
