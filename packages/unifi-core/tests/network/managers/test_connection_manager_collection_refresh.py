"""A handler refresh replaces the collection instead of merging into it (#963).

aiounifi's ``APIHandler.update()`` only adds and replaces items; it drops one
only when a websocket remove message names it, and ``ClientsAll`` and
``Devices`` have no remove messages at all. A long-running server therefore kept
client records forgotten on the controller (113 records against the UI's 76 in
the report), clients that had disconnected, and removed devices, until it
restarted.

These tests drive the real aiounifi handlers against a scripted
``controller.request`` so they exercise the library's own add/replace and
subscription behaviour, not a stand-in for it.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from aiounifi.errors import LoginRequired, RequestError
from aiounifi.interfaces.api_handlers import ItemEvent
from aiounifi.interfaces.clients import Clients
from aiounifi.interfaces.clients_all import ClientsAll
from aiounifi.interfaces.devices import Devices
from aiounifi.interfaces.dpi_restriction_apps import DPIRestrictionApps
from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.managers.connection_manager import ConnectionManager

MAC_KEPT = "02:00:00:00:00:01"
MAC_DELETED = "02:00:00:00:00:02"
MAC_NEW = "02:00:00:00:00:03"


def _ok(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"meta": {"rc": "ok"}, "data": rows}


class _Session:
    closed = False

    async def close(self) -> None:
        return None


class _Controller:
    """Fake aiounifi ``Controller``: real handlers, scripted ``request()`` replies.

    Each reply is a decoded body, an exception to raise, or a callable run
    while the request is "in flight" that returns the body.
    """

    def __init__(self) -> None:
        self.replies: list[Any] = []
        self.requested_paths: list[str] = []
        self.login_calls = 0
        self.messages = SimpleNamespace(subscribe=lambda *_args, **_kwargs: None)
        self.connectivity = SimpleNamespace(can_retry_login=True, config=SimpleNamespace(session=_Session()))
        self.clients = Clients(self)
        self.clients_all = ClientsAll(self)
        self.devices = Devices(self)
        self.dpi_apps = DPIRestrictionApps(self)

    async def request(self, api_request: Any) -> Any:
        self.requested_paths.append(api_request.path)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            return reply()
        return reply

    async def login(self) -> None:
        self.login_calls += 1


def _manager(controller: _Controller) -> ConnectionManager:
    manager = ConnectionManager("192.0.2.1", "admin", "secret")
    manager.controller = controller
    manager._aiohttp_session = controller.connectivity.config.session
    manager._initialized = True
    manager._auth_generation = 1
    return manager


def _client(mac: str, **extra: Any) -> dict[str, Any]:
    return {"mac": mac, **extra}


async def test_a_record_deleted_on_the_controller_leaves_clients_all():
    """The reported defect: a forgotten client stays in the full list."""
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [
        _ok([_client(MAC_KEPT), _client(MAC_DELETED, use_fixedip=True, fixed_ip="192.0.2.50")]),
        _ok([_client(MAC_KEPT)]),
    ]

    await manager.refresh_handler("clients_all")
    assert sorted(controller.clients_all) == [MAC_KEPT, MAC_DELETED]

    await manager.refresh_handler("clients_all")

    assert list(controller.clients_all) == [MAC_KEPT]
    assert controller.requested_paths == ["/rest/user", "/rest/user"]
    await manager.cleanup()


async def test_get_all_clients_stops_returning_a_forgotten_client():
    """End to end through ``ClientManager``, the path ``unifi_list_clients`` uses."""
    controller = _Controller()
    manager = _manager(controller)
    clients = ClientManager(manager)
    controller.replies = [
        _ok([_client(MAC_KEPT), _client(MAC_DELETED)]),
        _ok([_client(MAC_KEPT), _client(MAC_NEW)]),
    ]

    first = await clients.get_all_clients()
    assert len(first) == 2
    assert sorted(c.mac for c in first) == [MAC_KEPT, MAC_DELETED]

    manager._invalidate_cache()  # the 30 s list cache would otherwise answer
    second = await clients.get_all_clients()

    assert len(second) == 2
    assert sorted(c.mac for c in second) == [MAC_KEPT, MAC_NEW]
    await manager.cleanup()


async def test_a_disconnected_client_leaves_the_online_list():
    """``Clients`` removes only on a deleted user, so a disconnect used to linger as online."""
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [_ok([_client(MAC_KEPT), _client(MAC_DELETED)]), _ok([_client(MAC_KEPT)])]

    await manager.refresh_handler("clients")
    await manager.refresh_handler("clients")

    assert list(controller.clients) == [MAC_KEPT]
    assert controller.requested_paths == ["/stat/sta", "/stat/sta"]
    await manager.cleanup()


async def test_a_removed_device_leaves_the_device_list():
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [_ok([{"mac": MAC_KEPT}, {"mac": MAC_DELETED}]), _ok([{"mac": MAC_KEPT}])]

    await manager.refresh_handler("devices")
    await manager.refresh_handler("devices")

    assert list(controller.devices) == [MAC_KEPT]
    await manager.cleanup()


async def test_a_deleted_dpi_app_leaves_the_collection_keyed_by_id():
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [_ok([{"_id": "app-a"}, {"_id": "app-b"}]), _ok([{"_id": "app-a"}])]

    await manager.refresh_handler("dpi_apps")
    await manager.refresh_handler("dpi_apps")

    assert list(controller.dpi_apps) == ["app-a"]
    await manager.cleanup()


async def test_kept_records_take_the_new_data_and_new_records_are_added():
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [
        _ok([_client(MAC_KEPT, name="old")]),
        _ok([_client(MAC_KEPT, name="new"), _client(MAC_NEW, name="added")]),
    ]

    await manager.refresh_handler("clients_all")
    await manager.refresh_handler("clients_all")

    assert sorted(controller.clients_all) == [MAC_KEPT, MAC_NEW]
    assert controller.clients_all[MAC_KEPT].raw["name"] == "new"
    assert controller.clients_all[MAC_NEW].raw["name"] == "added"
    await manager.cleanup()


async def test_subscribers_are_told_a_dropped_record_was_deleted():
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [_ok([_client(MAC_KEPT), _client(MAC_DELETED)]), _ok([_client(MAC_KEPT)])]
    await manager.refresh_handler("clients_all")

    events: list[tuple[ItemEvent, str]] = []
    controller.clients_all.subscribe(lambda event, obj_id: events.append((event, obj_id)))
    await manager.refresh_handler("clients_all")

    assert events == [(ItemEvent.CHANGED, MAC_KEPT), (ItemEvent.DELETED, MAC_DELETED)]
    await manager.cleanup()


async def test_the_refresh_leaves_no_subscription_behind():
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [_ok([_client(MAC_KEPT)]), _ok([_client(MAC_KEPT)])]
    subscribers_before = {key: list(value) for key, value in controller.clients_all._subscribers.items()}

    await manager.refresh_handler("clients_all")

    async def _failed_reauthentication(_generation: int) -> bool:
        return False

    manager._reauthenticate = _failed_reauthentication
    controller.replies = [LoginRequired("expired")]
    with pytest.raises(RequestError):
        await manager.refresh_handler("clients_all")

    assert controller.clients_all._subscribers == subscribers_before
    await manager.cleanup()


NOT_A_SNAPSHOT = [
    pytest.param({}, id="non-JSON reply decodes to an empty body"),
    pytest.param({"meta": {"rc": "ok"}}, id="envelope without data"),
    pytest.param({"meta": {"rc": "ok"}, "data": None}, id="data is not a list"),
]


@pytest.mark.parametrize("reply", NOT_A_SNAPSHOT)
async def test_a_reply_that_is_not_a_snapshot_keeps_the_collection(reply):
    """A reply with no data list may be a failed read, so it never removes anything."""
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [_ok([_client(MAC_KEPT), _client(MAC_DELETED)]), reply]

    await manager.refresh_handler("clients_all")
    await manager.refresh_handler("clients_all")

    assert sorted(controller.clients_all) == [MAC_KEPT, MAC_DELETED]
    await manager.cleanup()


@pytest.mark.parametrize("reply", NOT_A_SNAPSHOT)
async def test_a_websocket_update_during_a_failed_read_removes_nothing(reply):
    """A websocket refresh of one client must not turn a non-snapshot into a prune of the rest."""
    controller = _Controller()
    manager = _manager(controller)

    def _websocket_update_then(reply_body: dict[str, Any]) -> Any:
        def _reply() -> dict[str, Any]:
            controller.clients.process_item(_client(MAC_KEPT, name="from websocket"))
            return reply_body

        return _reply

    controller.replies = [_ok([_client(MAC_KEPT), _client(MAC_DELETED)]), _websocket_update_then(reply)]

    await manager.refresh_handler("clients")
    await manager.refresh_handler("clients")

    assert sorted(controller.clients) == [MAC_KEPT, MAC_DELETED]
    assert controller.clients[MAC_KEPT].raw["name"] == "from websocket"
    await manager.cleanup()


async def test_an_empty_data_list_is_the_controllers_answer_and_empties_the_collection():
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [_ok([_client(MAC_KEPT), _client(MAC_DELETED)]), _ok([])]

    await manager.refresh_handler("clients")
    assert sorted(controller.clients) == [MAC_KEPT, MAC_DELETED]
    await manager.refresh_handler("clients")

    assert list(controller.clients) == []
    await manager.cleanup()


async def test_a_failed_refresh_keeps_the_collection():
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [_ok([_client(MAC_KEPT), _client(MAC_DELETED)]), RuntimeError("controller offline")]

    await manager.refresh_handler("clients_all")
    with pytest.raises(RequestError, match="refresh failed.*RuntimeError"):
        await manager.refresh_handler("clients_all")

    assert sorted(controller.clients_all) == [MAC_KEPT, MAC_DELETED]
    await manager.cleanup()


async def test_a_record_a_websocket_message_refreshes_mid_request_is_kept():
    """The list may predate a client that a websocket message adds while it is in flight."""
    controller = _Controller()
    manager = _manager(controller)

    def _reply_after_websocket_update() -> dict[str, Any]:
        controller.clients.process_item(_client(MAC_NEW))
        return _ok([_client(MAC_KEPT)])

    controller.replies = [_ok([_client(MAC_KEPT), _client(MAC_NEW)]), _reply_after_websocket_update]

    await manager.refresh_handler("clients")
    await manager.refresh_handler("clients")

    assert sorted(controller.clients) == [MAC_KEPT, MAC_NEW]
    await manager.cleanup()


async def test_the_retry_after_reauthentication_also_replaces_the_collection():
    controller = _Controller()
    manager = _manager(controller)

    async def _reauthenticate(_generation: int) -> bool:
        await controller.login()
        return True

    manager._reauthenticate = _reauthenticate
    controller.replies = [
        _ok([_client(MAC_KEPT), _client(MAC_DELETED)]),
        LoginRequired("expired"),
        _ok([_client(MAC_KEPT)]),
    ]

    await manager.refresh_handler("clients_all")
    await manager.refresh_handler("clients_all")

    assert controller.login_calls == 1
    assert list(controller.clients_all) == [MAC_KEPT]
    await manager.cleanup()
