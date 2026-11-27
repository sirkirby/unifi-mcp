"""SystemManager.list_all_users reads every page of the Users application's user search."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from unifi_core.access.managers import system_manager as system_module
from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.managers.system_manager import SystemManager
from unifi_core.exceptions import UniFiConnectionError


def _users(n: int, start: int = 0) -> list[dict]:
    return [
        {"unique_id": f"u{i}", "full_name": f"User {i}", "status": "ACTIVE", "roles": [{"name": "Viewer"}]}
        for i in range(start, start + n)
    ]


def _manager(pages: list[list[dict]], total: int | None) -> tuple[SystemManager, list[str]]:
    cm = AccessConnectionManager(host="192.0.2.1", username="admin", password="secret")
    cm._proxy_available = True
    cm._proxy_session = MagicMock()
    paths: list[str] = []

    async def request(method, path):
        paths.append(path)
        page_num = int(path.split("page_num=")[1].split("&")[0])
        rows = pages[page_num - 1] if page_num <= len(pages) else []
        envelope = {"code": 1, "data": rows, "page": page_num, "num": len(rows)}
        if total is not None:
            envelope["total"] = total
        return envelope

    cm.proxy_request_users = request
    return SystemManager(cm), paths


@pytest.mark.asyncio
async def test_reads_every_page_until_total(monkeypatch):
    monkeypatch.setattr(system_module, "_USER_PAGE_SIZE", 2)
    mgr, paths = _manager([_users(2), _users(2, 2), _users(1, 4)], total=5)

    users = await mgr.list_all_users()

    assert [u["unique_id"] for u in users] == ["u0", "u1", "u2", "u3", "u4"]
    assert len(paths) == 3
    assert all("page_size=2" in p for p in paths)


@pytest.mark.asyncio
async def test_stops_on_an_empty_page_without_a_total(monkeypatch):
    monkeypatch.setattr(system_module, "_USER_PAGE_SIZE", 2)
    mgr, paths = _manager([_users(2), _users(1, 2)], total=None)

    users = await mgr.list_all_users()

    assert len(users) == 3
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_limit_reads_only_the_pages_it_needs(monkeypatch):
    monkeypatch.setattr(system_module, "_USER_PAGE_SIZE", 2)
    mgr, paths = _manager([_users(2), _users(2, 2), _users(1, 4)], total=5)

    users = await mgr.list_all_users(limit=3)

    assert [u["unique_id"] for u in users] == ["u0", "u1", "u2"]
    assert len(paths) == 2


@pytest.mark.asyncio
async def test_a_small_limit_asks_for_a_small_page():
    mgr, paths = _manager([_users(3)], total=30)

    users = await mgr.list_all_users(limit=3)

    assert len(users) == 3
    assert "page_size=3" in paths[0]


@pytest.mark.asyncio
async def test_a_user_repeated_across_pages_is_listed_once(monkeypatch):
    monkeypatch.setattr(system_module, "_USER_PAGE_SIZE", 2)
    mgr, _ = _manager([_users(2), [_users(1, 1)[0], _users(1, 2)[0]]], total=3)

    users = await mgr.list_all_users()

    assert [u["unique_id"] for u in users] == ["u0", "u1", "u2"]


@pytest.mark.asyncio
async def test_compact_strips_each_user(monkeypatch):
    mgr, _ = _manager([_users(2)], total=2)

    users = await mgr.list_all_users(compact=True)

    assert all("roles" not in u and u["unique_id"] for u in users)


@pytest.mark.asyncio
async def test_page_bound_stops_a_runaway_read(monkeypatch):
    monkeypatch.setattr(system_module, "_USER_PAGE_SIZE", 1)
    monkeypatch.setattr(system_module, "_USER_MAX_PAGES", 3)
    mgr, paths = _manager([_users(1, i) for i in range(10)], total=10)

    users = await mgr.list_all_users()

    assert len(users) == 3
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_no_proxy_session_is_refused():
    mgr = SystemManager(AccessConnectionManager(host="192.0.2.1", username="", password=""))

    with pytest.raises(UniFiConnectionError, match="No auth path"):
        await mgr.list_all_users()
