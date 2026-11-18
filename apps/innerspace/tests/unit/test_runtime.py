"""Runtime singletons, response helpers and the category map."""

from __future__ import annotations

import logging

import pytest
from pydantic import BaseModel, ValidationError

from unifi_core.exceptions import UniFiNotFoundError
from unifi_innerspace_mcp import runtime
from unifi_innerspace_mcp.categories import INNERSPACE_CATEGORY_MAP, LAZY_DIRECT_TOOLS, TOOL_MODULE_MAP


def test_runtime_exposes_the_singletons_tool_modules_import():
    for name in (
        "config",
        "server",
        "connection_manager",
        "project_manager",
        "floor_plan_manager",
        "inventory_manager",
        "system_manager",
        "tool_registry",
    ):
        assert getattr(runtime, name) is not None, name
    assert runtime.project_manager._cm is runtime.connection_manager
    assert runtime.floor_plan_manager._cm is runtime.connection_manager
    assert runtime.inventory_manager._cm is runtime.connection_manager
    assert runtime.system_manager._cm is runtime.connection_manager


def test_category_map_is_the_four_tool_modules():
    assert INNERSPACE_CATEGORY_MAP == {
        "status": "status",
        "project": "project",
        "floor_plans": "floor_plans",
        "devices": "devices",
    }
    assert set(LAZY_DIRECT_TOOLS) == set(TOOL_MODULE_MAP)


def test_bundled_config_is_session_only():
    from pathlib import Path

    text = (Path(runtime.__file__).parent / "config" / "config.yaml").read_text(encoding="utf-8")
    settings = [line for line in text.splitlines() if not line.lstrip().startswith("#")]

    assert not any("API_KEY" in line or "api_key" in line for line in settings)
    assert "api_key" not in runtime.config.unifi


def test_connection_manager_is_built_from_the_session_settings(monkeypatch):
    monkeypatch.setenv("UNIFI_API_KEY", "console-local-key")
    monkeypatch.setenv("UNIFI_INNERSPACE_API_KEY", "console-local-key")
    manager = runtime.get_connection_manager.__wrapped__()

    assert manager.tls_env_prefix == "INNERSPACE"
    assert manager.authentication_status.api_key_configured is False


SECRET = "synthetic-value-0123"


def test_tool_success_redacts_by_policy(monkeypatch):
    payload = {"controller": {"password": SECRET}}
    monkeypatch.setattr(runtime, "should_redact_sensitive_fields", lambda: False)
    assert runtime.tool_success(payload) == {"success": True, "data": payload}

    monkeypatch.setattr(runtime, "should_redact_sensitive_fields", lambda: True)
    assert SECRET not in str(runtime.tool_success(payload))


class _Arguments(BaseModel):
    limit: int


def _validation_error() -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        _Arguments(limit="hunter2-rejected-value")
    return caught.value


def test_tool_failure_returns_core_text_for_core_errors(caplog):
    with caplog.at_level(logging.DEBUG):
        result = runtime.tool_failure("get project", UniFiNotFoundError("InnerSpace project", "p1"))

    assert result == {"success": False, "error": "Failed to get project: InnerSpace project 'p1' not found"}
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR] == [
        "Failed to get project: UniFiNotFoundError"
    ]


def test_tool_failure_for_invalid_arguments_is_fixed_text(caplog):
    with caplog.at_level(logging.DEBUG):
        result = runtime.tool_failure("list walls", _validation_error())

    assert result == {"success": False, "error": "Failed to list walls: invalid arguments"}
    assert "hunter2" not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


def test_tool_failure_for_anything_else_names_only_the_class(caplog):
    with caplog.at_level(logging.DEBUG):
        result = runtime.tool_failure("list walls", RuntimeError("https://192.0.2.9/secret-path"))

    assert result == {"success": False, "error": "Failed to list walls: unexpected RuntimeError"}
    assert "192.0.2.9" not in caplog.text


def test_tool_failure_does_not_repeat_the_operation():
    error = UniFiNotFoundError("floor plan", "InnerSpace", "get InnerSpace plan asset: no such floor plan")

    result = runtime.tool_failure("get InnerSpace plan asset", error)

    assert result == {"success": False, "error": "Failed to get InnerSpace plan asset: no such floor plan"}


def test_empty_port_and_verify_ssl_take_the_defaults(monkeypatch):
    # A compose file passes an unset variable as an empty string.
    monkeypatch.setenv("UNIFI_INNERSPACE_HOST", "192.0.2.10")
    monkeypatch.setenv("UNIFI_INNERSPACE_USERNAME", "synthetic-admin")
    monkeypatch.setenv("UNIFI_INNERSPACE_PASSWORD", "synthetic-password-0123456789")
    monkeypatch.setenv("UNIFI_INNERSPACE_PORT", "")
    monkeypatch.setenv("UNIFI_INNERSPACE_VERIFY_SSL", "")
    monkeypatch.setattr(runtime, "get_config", runtime.load_config)

    manager = runtime.get_connection_manager.__wrapped__()

    assert (manager.host, manager.port) == ("192.0.2.10", 443)
    assert runtime._tls_settings(runtime.get_config().unifi) == (False, None)


def test_there_is_no_site_setting(monkeypatch):
    # InnerSpace sites are a read filter (site_id), not a server setting.
    monkeypatch.setenv("UNIFI_INNERSPACE_SITE", "synthetic-site")

    assert "site" not in runtime.load_config().unifi
