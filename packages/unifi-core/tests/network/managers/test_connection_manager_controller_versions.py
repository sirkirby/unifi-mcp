"""Network keeps the controller's versions in memory for the support bundle.

The bundle's summary probe never contacts the controller and its connectivity
probe returns only a fixed outcome, so the versions are read once on connecting
and stay available to both.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from unifi_core.network.managers import connection_manager as module
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.support_bundle import ControllerSection, safe_controller_version


def _sysinfo(**fields: Any) -> dict[str, Any]:
    return {"meta": {"rc": "ok"}, "data": [{"version": "11.0.99", "console_display_version": "6.0.16", **fields}]}


def _versions(manager: ConnectionManager) -> tuple[str | None, str | None]:
    status = manager.support_status()
    return status["application_version"], status["unifi_os_version"]


async def _connect(request: AsyncMock) -> tuple[ConnectionManager, bool]:
    controller = MagicMock()
    controller.login = AsyncMock()
    controller.request = request
    manager = ConnectionManager("192.0.2.1", "admin", "secret", max_retries=1)
    with (
        patch.object(module, "Controller", return_value=controller),
        patch("unifi_core.network.controller_type.resolve_controller_type", return_value="proxy"),
    ):
        connected = await manager.initialize()
    return manager, connected


async def test_connecting_remembers_both_versions():
    request = AsyncMock(return_value=_sysinfo())

    manager, connected = await _connect(request)

    assert connected is True
    assert _versions(manager) == ("11.0.99", "6.0.16")
    request.assert_awaited_once()
    assert request.await_args.args[0].path == "/stat/sysinfo"
    await manager.cleanup()


async def test_a_sysinfo_record_outside_a_list_is_read_too():
    """``SystemManager.get_system_info`` already accepts this form."""
    manager, _ = await _connect(AsyncMock(return_value={"data": {"version": "11.0.99"}}))

    assert _versions(manager) == ("11.0.99", None)
    await manager.cleanup()


async def test_a_failed_read_on_reconnecting_does_not_keep_the_old_versions():
    """The controller may have been upgraded while the connection was down."""
    manager, _ = await _connect(AsyncMock(return_value=_sysinfo()))
    assert _versions(manager) == ("11.0.99", "6.0.16")

    manager.controller.request = AsyncMock(side_effect=RuntimeError("private detail"))
    await manager._read_controller_versions()

    assert _versions(manager) == (None, None)
    await manager.cleanup()


async def test_the_read_uses_the_controller_type_found_after_login():
    """Detection can change its answer after login, and the wrong one selects the wrong API prefix."""
    manager, _ = await _connect(AsyncMock(return_value=_sysinfo()))
    controller = manager.controller
    controller.connectivity.is_unifi_os = True
    manager._unifi_os_override = False
    seen: list[bool] = []

    async def _request(_api_request: Any) -> dict[str, Any]:
        seen.append(controller.connectivity.is_unifi_os)
        return _sysinfo()

    controller.request = AsyncMock(side_effect=_request)
    await manager._read_controller_versions()

    assert seen == [False]
    await manager.cleanup()


async def test_losing_the_connection_forgets_the_versions():
    """A fallback to the API-key route reports connected, so old versions would pass as current."""
    manager, _ = await _connect(AsyncMock(return_value=_sysinfo()))
    assert _versions(manager) == ("11.0.99", "6.0.16")

    await manager._discard_connection()

    assert _versions(manager) == (None, None)
    await manager.cleanup()


async def test_a_controller_without_a_console_version_has_only_the_application_version():
    manager, _ = await _connect(AsyncMock(return_value={"data": [{"version": "9.0.0"}]}))

    assert _versions(manager) == ("9.0.0", None)
    await manager.cleanup()


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param({}, id="non-JSON page"),
        pytest.param({"data": []}, id="empty list"),
        pytest.param({"data": "nope"}, id="data is not a list"),
        pytest.param({"data": ["nope"]}, id="row is not a mapping"),
        pytest.param(None, id="no reply"),
    ],
)
async def test_an_unusable_reply_still_connects_without_versions(reply):
    manager, connected = await _connect(AsyncMock(return_value=reply))

    assert connected is True
    assert _versions(manager) == (None, None)
    await manager.cleanup()


async def test_a_failed_read_still_connects():
    manager, connected = await _connect(AsyncMock(side_effect=RuntimeError("private detail")))

    assert connected is True
    assert _versions(manager) == (None, None)
    await manager.cleanup()


async def test_a_slow_read_does_not_hold_up_the_connection():
    async def _never(_request: Any) -> None:
        await asyncio.Event().wait()

    with patch.object(module, "_CONTROLLER_VERSION_READ_TIMEOUT_SECONDS", 0.01):
        manager, connected = await _connect(AsyncMock(side_effect=_never))

    assert connected is True
    assert _versions(manager) == (None, None)
    await manager.cleanup()


async def test_a_later_read_updates_the_versions_and_cleanup_clears_them():
    manager, _ = await _connect(AsyncMock(return_value=_sysinfo()))

    manager.remember_controller_versions({"version": "11.1.0", "console_display_version": "6.1.0"})
    assert _versions(manager) == ("11.1.0", "6.1.0")

    await manager.cleanup()
    assert _versions(manager) == (None, None)


def test_a_value_the_bundle_would_reject_is_dropped_on_its_own():
    """The bundle's schema raises on an unsafe version, which would cost the whole bundle."""
    manager = ConnectionManager("192.0.2.1", "admin", "secret")

    manager.remember_controller_versions({"version": "<img src=x>", "console_display_version": "6.0.16"})

    application_version, unifi_os_version = _versions(manager)
    assert application_version is None
    assert unifi_os_version == "6.0.16"
    ControllerSection(
        status="available",
        api_surface="controller_v2",
        application_version=application_version,
        unifi_os_version=unifi_os_version,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("11.0.99", "11.0.99"),
        ("6.0.16", "6.0.16"),
        ("not a version", None),
        ("1" * 65, None),
        ("", None),
        (None, None),
        (11, None),
    ],
)
def test_safe_controller_version(value, expected):
    assert safe_controller_version(value) == expected
