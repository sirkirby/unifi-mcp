"""A handler refresh replaces the collection instead of merging into it.

aiounifi's ``APIHandler.update()`` only adds and replaces items; it drops one
only when a websocket remove message names it, and ``ClientsAll`` and
``Devices`` have no remove messages at all. A long-running server therefore kept
client records forgotten on the controller, clients that had disconnected, and
removed devices, until it restarted.

These tests drive the real aiounifi handlers against a scripted
``controller.request`` so they exercise the library's own add/replace and
subscription behaviour, not a stand-in for it.
"""

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import pytest
from aiounifi.errors import LoginRequired, RequestError
from aiounifi.interfaces.api_handlers import ItemEvent
from aiounifi.interfaces.clients import Clients
from aiounifi.interfaces.clients_all import ClientsAll
from aiounifi.interfaces.devices import Devices
from aiounifi.interfaces.dpi_restriction_apps import DPIRestrictionApps
from unifi_core.network.managers.client_manager import REST_USER_ROW_CAP, ClientManager
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

    Each reply is a decoded body, an exception to raise, or a callable, sync or
    async, run while the request is "in flight" that returns the body.
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
            reply = reply()
        return await reply if inspect.isawaitable(reply) else reply

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
    pytest.param(_ok([{"unexpected": "shape"}]), id="rows without the id key"),
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
async def test_a_refresh_reports_a_reply_that_is_not_a_snapshot(reply):
    """A caller must be able to tell a failed read from a list it can trust."""
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [reply]

    assert await manager.refresh_handler("clients_all") is False
    await manager.cleanup()


@pytest.mark.parametrize(
    "rows",
    [pytest.param([], id="empty list"), pytest.param([_client(MAC_KEPT)], id="listed rows")],
)
async def test_a_refresh_reports_a_list_it_can_trust(rows):
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [_ok(rows)]

    assert await manager.refresh_handler("clients_all") is True
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


@pytest.mark.parametrize(
    ("rows_listed", "unlisted_record_kept"),
    [
        pytest.param(REST_USER_ROW_CAP, True, id="full window may have left the record out"),
        pytest.param(REST_USER_ROW_CAP - 1, False, id="below the cap the list is complete"),
    ],
)
async def test_a_reply_at_the_row_cap_does_not_prove_a_record_is_gone(rows_listed, unlisted_record_kept):
    controller = _Controller()
    manager = _manager(controller)
    rows = [_client(f"02:00:01:{i >> 8 & 255:02x}:{i & 255:02x}:00") for i in range(rows_listed)]
    controller.replies = [_ok([_client(MAC_KEPT)]), _ok(rows)]

    await manager.refresh_handler("clients_all")
    await manager.refresh_handler("clients_all")

    assert (MAC_KEPT in controller.clients_all) is unlisted_record_kept
    assert len(list(controller.clients_all)) == rows_listed + (1 if unlisted_record_kept else 0)
    await manager.cleanup()


async def test_the_row_cap_applies_only_to_the_capped_endpoint():
    """A complete online list of the same length still removes a disconnected client."""
    controller = _Controller()
    manager = _manager(controller)
    rows = [_client(f"02:00:01:{i >> 8 & 255:02x}:{i & 255:02x}:00") for i in range(REST_USER_ROW_CAP)]
    controller.replies = [_ok([_client(MAC_DELETED)]), _ok(rows)]

    await manager.refresh_handler("clients")
    await manager.refresh_handler("clients")

    assert controller.requested_paths == ["/stat/sta", "/stat/sta"]
    assert MAC_DELETED not in controller.clients
    assert len(list(controller.clients)) == REST_USER_ROW_CAP
    await manager.cleanup()


def _held_until(release: asyncio.Event, body: dict[str, Any]) -> Any:
    async def _reply() -> dict[str, Any]:
        await release.wait()
        return body

    return _reply


async def _let_tasks_run() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.mark.parametrize("older_reply_lands_first", [True, False], ids=["older reply first", "newer reply first"])
async def test_overlapping_refreshes_end_on_the_newest_snapshot(older_reply_lands_first):
    """An older reply neither shields a record from a newer one nor brings it back."""
    controller = _Controller()
    manager = _manager(controller)
    controller.replies = [_ok([_client(MAC_KEPT), _client(MAC_DELETED)])]
    await manager.refresh_handler("clients_all")

    older_release, newer_release = asyncio.Event(), asyncio.Event()
    controller.replies = [
        _held_until(older_release, _ok([_client(MAC_KEPT), _client(MAC_DELETED)])),
        _held_until(newer_release, _ok([_client(MAC_KEPT)])),
    ]
    older = asyncio.create_task(manager.refresh_handler("clients_all"))
    await _let_tasks_run()
    newer = asyncio.create_task(manager.refresh_handler("clients_all"))
    await _let_tasks_run()

    for release in (older_release, newer_release) if older_reply_lands_first else (newer_release, older_release):
        release.set()
        await _let_tasks_run()
    await asyncio.gather(older, newer)

    assert list(controller.clients_all) == [MAC_KEPT]
    await manager.cleanup()


async def test_a_slow_refresh_does_not_hold_up_another_collection():
    controller = _Controller()
    manager = _manager(controller)
    release = asyncio.Event()
    controller.replies = [_held_until(release, _ok([_client(MAC_KEPT)])), _ok([_client(MAC_NEW)])]

    slow = asyncio.create_task(manager.refresh_handler("clients"))
    await _let_tasks_run()
    await asyncio.wait_for(manager.refresh_handler("clients_all"), timeout=1)

    assert list(controller.clients_all) == [MAC_NEW]
    release.set()
    await slow
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
