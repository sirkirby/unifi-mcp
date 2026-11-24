"""Tests for ProtectConnectionManager public API guardrails."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.managers.id_portability import compare_id_portability


def _make_connection_manager(api_key: str | None = None, tls_env_prefix: str | None = None) -> ProtectConnectionManager:
    return ProtectConnectionManager(
        host="protect.example.test",
        username="admin",
        password="secret",
        api_key=api_key,
        tls_env_prefix=tls_env_prefix,
    )


@pytest.mark.parametrize(
    ("api_key", "expected"),
    [
        ("protect-api-key", True),
        (None, False),
        ("", False),
        ("   ", False),
    ],
)
def test_has_api_key_is_true_only_when_api_key_is_configured(api_key: str | None, expected: bool) -> None:
    cm = _make_connection_manager(api_key=api_key)

    assert cm.has_api_key is expected


def test_require_public_api_key_returns_cleanly_when_configured() -> None:
    cm = _make_connection_manager(api_key="protect-api-key")

    cm.require_public_api_key("update sensor settings")


def test_require_public_api_key_names_server_variables_for_an_mcp_caller() -> None:
    cm = _make_connection_manager(tls_env_prefix="PROTECT")

    with pytest.raises(ValueError) as exc_info:
        cm.require_public_api_key("update sensor settings")

    message = str(exc_info.value)
    assert "update sensor settings" in message
    assert "Set UNIFI_PROTECT_API_KEY (or UNIFI_API_KEY on the UNIFI_HOST console) and restart the server." in message


def test_require_public_api_key_points_at_the_controller_record_without_a_prefix() -> None:
    cm = _make_connection_manager()

    with pytest.raises(ValueError) as exc_info:
        cm.require_public_api_key("update sensor settings")

    message = str(exc_info.value)
    assert "update sensor settings" in message
    assert "Add one to this controller's configuration." in message
    assert "UNIFI_" not in message


@pytest.mark.parametrize("resource_type", ["sensors", "chimes", "viewers", "liveviews", "cameras"])
def test_id_portability_helper_accepts_matching_ids_for_adopted_capabilities(resource_type: str) -> None:
    report = compare_id_portability(
        resource_type=resource_type,
        bootstrap_items={"same-id": object()},
        public_items=[SimpleNamespace(id="same-id")],
    )

    assert report.portable is True
    assert report.bootstrap_ids == ("same-id",)
    assert report.public_ids == ("same-id",)
    assert report.missing_from_public == ()
    assert report.missing_from_bootstrap == ()


def test_id_portability_helper_raises_on_independent_id_mismatch() -> None:
    with pytest.raises(ValueError) as exc_info:
        compare_id_portability(
            resource_type="sensors",
            bootstrap_items={"private-sensor-id": object()},
            public_items=[{"id": "public-sensor-id"}],
            raise_on_mismatch=True,
        )

    message = str(exc_info.value)
    assert "sensors" in message
    assert "private-sensor-id" in message
    assert "public-sensor-id" in message


@pytest.mark.asyncio
async def test_connection_manager_validates_public_id_portability_without_tool_layer() -> None:
    cm = _make_connection_manager(api_key="protect-api-key")
    cm._initialized = True
    cm._client = SimpleNamespace(
        bootstrap=SimpleNamespace(sensors={"sensor-abc": object()}),
        get_sensors_public=AsyncMock(return_value=[SimpleNamespace(id="sensor-abc")]),
    )

    report = await cm.validate_public_id_portability(
        resource_type="sensors",
        bootstrap_collection="sensors",
        public_list_method="get_sensors_public",
    )

    assert report.portable is True
    assert report.bootstrap_ids == report.public_ids == ("sensor-abc",)
    cm._client.get_sensors_public.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_connection_manager_id_portability_check_requires_api_key() -> None:
    cm = _make_connection_manager()

    with pytest.raises(ValueError, match="requires an API key"):
        await cm.validate_public_id_portability(
            resource_type="sensors",
            bootstrap_collection="sensors",
            public_list_method="get_sensors_public",
        )
