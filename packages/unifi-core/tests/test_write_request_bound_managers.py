"""Controller requests inside a held write are bounded by the write's hold budget.

Network sends through aiounifi, Access through its proxy session, and InnerSpace
and Drive through their console sessions; none of them has a request timeout as
short as a write's hold budget. Inside
a held write each request is cut off when the write's budget runs out, and the
caller is told the change may or may not have been applied. Outside a write
nothing changes.

Every transport that can carry a write is bounded, so a request that went out
marks the write ticket: a later request refused for budget must not report the
write as unsent.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiounifi.models.api import ApiRequest
from innerspace_stub import HOST, PASSWORD, USERNAME, console  # noqa: F401  (console: a fixture, by name)
from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.auth import UniFiAuth
from unifi_core.drive.managers.connection_manager import DriveConnectionManager, DriveWriteNotSent
from unifi_core.drive.managers.file_service_manager import FileServiceManager
from unifi_core.drive.managers.shared_drive_manager import SharedDriveManager
from unifi_core.innerspace.managers.connection_manager import (
    INTERNAL_PROJECT_PATH,
    SHAPE_CHANGE_PATH,
    InnerSpaceConnectionManager,
    InnerSpaceWriteOutcomeUnknown,
    InnerSpaceWriteOutOfTime,
)
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.firewall_manager import FirewallManager
from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.operation_gate import GateSettings, OperationGate, WriteRequestTimeout

from tests.drive import fixtures as drive_fx
from tests.drive.conftest import HOST as DRIVE_HOST
from tests.drive.conftest import PASSWORD as DRIVE_PASSWORD
from tests.drive.conftest import USERNAME as DRIVE_USERNAME
from tests.drive.conftest import StubConsole


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def _nearly_spent_gate() -> tuple[OperationGate, _Clock]:
    clock = _Clock()
    return OperationGate(GateSettings(hold_budget_seconds=10), name="test", clock=clock), clock


class _Session:
    closed = False

    async def close(self):
        return None


def _network(slow_seconds: float) -> ConnectionManager:
    manager = ConnectionManager("controller.example", "admin", "pw")
    controller = MagicMock()
    controller.connectivity.config.session = _Session()
    controller.connectivity.is_unifi_os = True

    async def _request(api_request):
        await asyncio.sleep(slow_seconds)
        return {"data": [{"ok": True}]}

    controller.request = _request
    manager.controller = controller
    manager._aiohttp_session = controller.connectivity.config.session
    manager._initialized = True
    manager._auth_generation = 1
    return manager


@pytest.mark.parametrize("path", ["/rest/networkconf/abc", "/set/setting/mgmt"])
async def test_network_request_inside_a_held_write_stops_at_the_budget(path) -> None:
    manager = _network(slow_seconds=1)
    gate, clock = _nearly_spent_gate()

    async with gate.write():
        clock.value = 9.99
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied"):
            await manager.request(ApiRequest(method="put", path=path, data={"name": "x"}))


async def test_network_request_outside_a_write_is_not_bounded() -> None:
    manager = _network(slow_seconds=0.02)
    gate, clock = _nearly_spent_gate()
    async with gate.read():
        clock.value = 9.999
        assert await manager.request(ApiRequest(method="get", path="/rest/networkconf")) == [{"ok": True}]


def _access_response() -> AsyncMock:
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"code": "SUCCESS", "data": {"ok": True}})

    async def _slow_enter(*_args):
        await asyncio.sleep(1)
        return response

    response.__aenter__ = _slow_enter
    response.__aexit__ = AsyncMock(return_value=False)
    return response


async def test_access_proxy_request_inside_a_held_write_stops_at_the_budget() -> None:
    cm = AccessConnectionManager(host="access.example", username="admin", password="pw")
    session = MagicMock()
    session.request = MagicMock(return_value=_access_response())
    cm._proxy_session = session
    cm._proxy_available = True
    cm._csrf_token = "csrf"
    gate, clock = _nearly_spent_gate()

    async with gate.write():
        clock.value = 9.99
        with pytest.raises(WriteRequestTimeout):
            await cm.proxy_request("PUT", "doors/1", json={"name": "x"})
    # The proxy session survives: a timed-out write is not an auth failure.
    assert cm._proxy_session is session


def _plain_response(status: int) -> AsyncMock:
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value={"code": 0, "data": {"ok": True}})
    response.text = AsyncMock(return_value="")
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


async def test_access_re_login_runs_outside_the_write_budget() -> None:
    cm = AccessConnectionManager(host="access.example", username="admin", password="pw")
    session = MagicMock()
    session.request = MagicMock(side_effect=[_plain_response(401), _plain_response(200)])
    cm._proxy_session = session
    cm._proxy_available = True
    cm._csrf_token = "old"

    async def slow_login() -> None:
        # Longer than the write has left: a login cut off here could leave
        # the cookie and CSRF token mismatched.
        await asyncio.sleep(0.05)
        cm._csrf_token = "new"

    cm._proxy_login = slow_login
    gate, clock = _nearly_spent_gate()

    async with gate.write():
        clock.value = 9.98
        payload = await cm.proxy_request("PUT", "doors/1", json={"name": "x"})
    assert payload["data"] == {"ok": True}
    assert session.request.call_args_list[1].kwargs["headers"] == {"X-CSRF-Token": "new"}


class _Answer:
    """An ``async with session.request(...)`` answer; ``on_enter`` runs when the request goes out."""

    def __init__(self, *, status: int = 200, body=None, on_enter=None) -> None:
        self.status = status
        self._body = body
        self._on_enter = on_enter

    async def __aenter__(self):
        if self._on_enter is not None:
            await self._on_enter()
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def json(self, *args, **kwargs):
        return self._body

    async def text(self):
        return ""


async def test_a_zone_create_whose_read_back_is_refused_still_reports_the_create_as_sent() -> None:
    auth = UniFiAuth(api_key="synthetic-key")
    connection = _network(slow_seconds=0)
    manager = FirewallManager(connection, auth)
    manager._require_zone_mutation_session = AsyncMock()
    manager._get_integration_site_id = AsyncMock(return_value="site")
    gate, clock = _nearly_spent_gate()
    posts: list[str] = []

    async def the_post_uses_up_the_budget() -> None:
        posts.append("post")
        clock.value = 11

    session = MagicMock()
    session.request = MagicMock(return_value=_Answer(body={"id": "public-id"}, on_enter=the_post_uses_up_the_budget))
    session.close = AsyncMock()
    auth.get_api_key_session = AsyncMock(return_value=session)

    async with gate.write() as ticket:
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied") as refused:
            await manager.create_firewall_zone("Synthetic")
    assert posts == ["post"]
    assert refused.value.request_sent is True
    assert ticket.request_sent is True
    assert ticket.cut_off is refused.value


async def test_a_zone_write_on_the_integration_api_stops_at_the_budget() -> None:
    auth = UniFiAuth(api_key="synthetic-key")
    manager = FirewallManager(_network(slow_seconds=0), auth)

    async def hang() -> None:
        await asyncio.sleep(1)

    session = MagicMock()
    session.request = MagicMock(return_value=_Answer(body={}, on_enter=hang))
    session.close = AsyncMock()
    auth.get_api_key_session = AsyncMock(return_value=session)
    gate, clock = _nearly_spent_gate()

    async with gate.write() as ticket:
        clock.value = 9.99
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied"):
            await manager._request_integration_api("delete", "/v1/sites/site/firewall/zones/zone")
    assert ticket.request_sent is True
    session.close.assert_awaited_once()


def _restore_manager(answer: _Answer) -> tuple[SystemManager, MagicMock]:
    connection = MagicMock()
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.url_base = "https://controller.example"
    connection.site = "default"
    post = MagicMock(return_value=answer)
    connection.controller.session.post = post
    return SystemManager(connection), post


async def test_a_restore_upload_inside_a_held_write_stops_at_the_budget() -> None:
    async def hang() -> None:
        await asyncio.sleep(1)

    manager, post = _restore_manager(_Answer(on_enter=hang))
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        clock.value = 9.99
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied"):
            await manager.restore_backup(b"backup")
    assert ticket.request_sent is True
    post.assert_called_once()


async def test_a_restore_upload_with_no_budget_left_is_not_sent() -> None:
    manager, post = _restore_manager(_Answer())
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        clock.value = 11
        with pytest.raises(WriteRequestTimeout, match="not sent") as refused:
            await manager.restore_backup(b"backup")
    assert refused.value.request_sent is False
    assert ticket.request_sent is False
    post.assert_not_called()


def _developer_api(answer: _Answer) -> tuple[AccessConnectionManager, MagicMock]:
    cm = AccessConnectionManager(host="access.example", username="", password="", api_key="synthetic-token")
    session = MagicMock()
    session.request = MagicMock(return_value=answer)
    cm._api_session = session
    cm._api_client = MagicMock()
    cm._api_client_available = True
    return cm, session


async def test_an_access_developer_api_write_inside_a_held_write_stops_at_the_budget() -> None:
    async def hang() -> None:
        await asyncio.sleep(1)

    cm, session = _developer_api(_Answer(on_enter=hang))
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        clock.value = 9.99
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied"):
            await cm.developer_request("POST", "visitors", operation="Create visitor", json={"first_name": "x"})
    assert ticket.request_sent is True
    session.request.assert_called_once()


async def test_an_access_developer_api_write_with_no_budget_left_is_not_sent() -> None:
    cm, session = _developer_api(_Answer())
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        clock.value = 11
        with pytest.raises(WriteRequestTimeout, match="not sent"):
            await cm.developer_request("POST", "visitors", operation="Create visitor", json={"first_name": "x"})
    assert ticket.request_sent is False
    session.request.assert_not_called()


async def test_an_access_sdk_door_write_inside_a_held_write_stops_at_the_budget(monkeypatch) -> None:
    sent: list[str] = []

    async def hang() -> None:
        await asyncio.sleep(1)

    def request(method, url, **kwargs):
        sent.append(method)
        if len(sent) == 1:  # the SDK's authentication read at connect
            return _Answer(body={"code": "SUCCESS", "data": []})
        return _Answer(on_enter=hang)

    session = MagicMock(closed=False)
    session.request = request
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kwargs: session)
    cm = AccessConnectionManager(host="access.example", username="", password="", api_key="synthetic-token")
    await cm._try_api_client()
    assert cm.has_api_client

    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        clock.value = 9.99
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied"):
            await cm.api_client.unlock_door("door-1")
    assert sent == ["GET", "PUT"]
    assert ticket.request_sent is True


# InnerSpace: its session client bounds every request but the login and logout.

_SHAPE_CHANGE = {"create": [], "update": [], "remove": [], "mode": "2D"}


@pytest.fixture
async def innerspace(console):  # noqa: F811
    """An InnerSpace session client logged in to the loopback console stub."""
    cm = InnerSpaceConnectionManager(HOST, USERNAME, PASSWORD, base_url=console.base_url)
    assert await cm.initialize() is True
    yield cm
    await cm.close()


async def test_an_innerspace_write_with_no_budget_left_is_not_sent(innerspace, console) -> None:  # noqa: F811
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        clock.value = 11
        with pytest.raises(InnerSpaceWriteOutOfTime, match="nothing was changed"):
            await innerspace.request("POST", SHAPE_CHANGE_PATH, operation="write", json=_SHAPE_CHANGE, replay=False)
    assert console.writes() == []
    assert ticket.request_sent is False
    assert ticket.cut_off is not None and ticket.cut_off.request_sent is False


async def test_an_innerspace_write_cut_off_after_sending_is_unknown(innerspace, console) -> None:  # noqa: F811
    console.reply("POST", SHAPE_CHANGE_PATH, {"data": {}}, delay=1)
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        clock.value = 9.99
        with pytest.raises(InnerSpaceWriteOutcomeUnknown, match="whether it was applied is unknown"):
            await innerspace.request("POST", SHAPE_CHANGE_PATH, operation="write", json=_SHAPE_CHANGE, replay=False)
    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == 1
    assert ticket.request_sent is True
    assert ticket.cut_off is not None and ticket.cut_off.request_sent is True


async def test_an_innerspace_read_inside_a_held_write_stops_at_the_budget(innerspace, console) -> None:  # noqa: F811
    console.reply("GET", INTERNAL_PROJECT_PATH, {"data": {}}, delay=1)
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        clock.value = 9.99
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied"):
            await innerspace.request("GET", INTERNAL_PROJECT_PATH, operation="read")
    assert ticket.request_sent is True


async def test_an_innerspace_re_login_runs_outside_the_write_budget(innerspace, console) -> None:  # noqa: F811
    """The budget runs out while the session is renewed: the login still goes out, the retry does not."""
    console.expire_session()
    gate, clock = _nearly_spent_gate()
    renew = innerspace._relogin

    async def relogin_after_the_budget(*args, **kwargs):
        clock.value = 11
        return await renew(*args, **kwargs)

    innerspace._relogin = relogin_after_the_budget
    async with gate.write():
        clock.value = 5
        with pytest.raises(WriteRequestTimeout, match="ran out before it finished"):
            await innerspace.request("GET", INTERNAL_PROJECT_PATH, operation="read")
    assert console.logins == 2
    assert len(console.calls("GET", INTERNAL_PROJECT_PATH)) == 1


async def test_an_innerspace_request_outside_a_write_is_not_bounded(innerspace, console) -> None:  # noqa: F811
    console.reply("GET", INTERNAL_PROJECT_PATH, {"data": {"ok": True}}, delay=0.02)
    gate, clock = _nearly_spent_gate()
    async with gate.read():
        clock.value = 9.999
        assert await innerspace.request("GET", INTERNAL_PROJECT_PATH, operation="read") == {"data": {"ok": True}}


# Drive: its session client bounds every request but the login and logout. A
# change request the budget stopped before sending is not sent, even when the
# write's earlier reads went out.

_NFS = "/proxy/drive/api/v1/services/nfs/advanced-settings"
_NFS_BODY = {"connections": []}


@pytest.fixture
async def drive_console():
    """A Drive console stub on loopback."""
    stub = StubConsole()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", stub.handle)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    stub.base_url = str(server.make_url("")).rstrip("/")
    yield stub
    await server.close()


@pytest.fixture
async def drive(drive_console):
    cm = DriveConnectionManager(DRIVE_HOST, DRIVE_USERNAME, DRIVE_PASSWORD, base_url=drive_console.base_url)
    yield cm
    await cm.close()


def _drive_logins(stub: StubConsole) -> int:
    return len(stub.calls("POST", "/api/auth/login"))


async def test_a_drive_change_with_no_budget_left_is_not_sent(drive, drive_console) -> None:
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        clock.value = 11
        with pytest.raises(DriveWriteNotSent, match="nothing was changed"):
            await drive.put(_NFS, _NFS_BODY)
    assert drive_console.writes == []
    assert ticket.request_sent is False


async def test_a_drive_change_after_its_reads_with_no_budget_left_is_still_not_sent(drive, drive_console) -> None:
    drive_console.reply("GET", _NFS, drive_fx.nfs_advanced())
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        await drive.get(_NFS)
        clock.value = 11
        with pytest.raises(DriveWriteNotSent, match="nothing was changed"):
            await drive.put(_NFS, _NFS_BODY)
    assert drive_console.writes == []
    # The ticket counts the read as sent; the change itself was not.
    assert ticket.request_sent is True


async def test_a_drive_change_cut_off_after_sending_is_unknown(drive, drive_console) -> None:
    drive_console.reply("PUT", _NFS, {"err": None, "type": "single", "data": {}}, delay=1)
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        clock.value = 9.99
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied") as cut:
            await drive.put(_NFS, _NFS_BODY)
    assert not isinstance(cut.value, DriveWriteNotSent)
    assert len(drive_console.calls("PUT", _NFS)) == 1
    assert ticket.request_sent is True
    assert ticket.cut_off is not None and ticket.cut_off.request_sent is True


async def test_a_drive_re_login_runs_outside_the_write_budget(drive, drive_console) -> None:
    """The budget runs out while the session is renewed: the login still goes out, the retry does not."""
    drive_console.reply("GET", _NFS, drive_fx.nfs_advanced())
    drive_console.reply("PUT", _NFS, {"err": {"msg": "expired"}}, status=401)
    gate, clock = _nearly_spent_gate()
    login = drive._login

    async def login_after_the_budget() -> None:
        await login()
        clock.value = 11

    async with gate.write():
        await drive.get(_NFS)
        drive._login = login_after_the_budget
        clock.value = 5
        # The console refused the session without acting on the PUT, and the retry was never sent.
        with pytest.raises(DriveWriteNotSent, match="nothing was changed"):
            await drive.put(_NFS, _NFS_BODY)
    assert _drive_logins(drive_console) == 2
    assert len(drive_console.calls("PUT", _NFS)) == 1


async def test_a_drive_nfs_change_whose_last_re_read_runs_out_of_budget_is_not_sent(drive, drive_console) -> None:
    files = FileServiceManager(drive, SharedDriveManager(drive))
    drive_console.reply("GET", _NFS, drive_fx.nfs_advanced())
    # The re-read just before the PUT outlasts the budget.
    drive_console.reply("GET", _NFS, drive_fx.nfs_advanced(), delay=1)
    gate, clock = _nearly_spent_gate()
    async with gate.write() as ticket:
        change = await files.plan_remove_nfs_connection(drive_fx.CLIENT)
        clock.value = 9.99
        with pytest.raises(DriveWriteNotSent, match="nothing was changed"):
            await files.apply_nfs_change(change)
    assert drive_console.calls("PUT", _NFS) == []
    assert ticket.request_sent is True


async def test_a_drive_request_outside_a_write_is_not_bounded(drive, drive_console) -> None:
    drive_console.reply("GET", _NFS, drive_fx.nfs_advanced(), delay=0.02)
    gate, clock = _nearly_spent_gate()
    async with gate.read():
        clock.value = 9.999
        assert await drive.get(_NFS) == drive_fx.nfs_advanced()["data"]
