"""``/api/system`` without the app list: the public payload UniFi OS serves to a missing or expired session.

On InnerSpace 1.4.3 the console answers that route with 200 and a public payload for
no session or an invalid one, never 401 or 403. The stub does the same.
"""

import asyncio
import json
from pathlib import Path

import pytest
from unifi_core.exceptions import UniFiPermissionError
from unifi_core.innerspace.managers._writes import ensure_writable, send_write
from unifi_core.innerspace.managers.connection_manager import SHAPE_CHANGE_PATH, SYSTEM_PATH
from unifi_core.innerspace.managers.system_manager import InnerSpaceSystemManager

from tests.innerspace.conftest import LOGOUT
from tests.innerspace.helpers import new_wall, ready, stored_shape

FIXTURES = Path(__file__).parent / "fixtures"
OP = "Read InnerSpace status"
WALL_1 = "00000000-0000-4000-8000-0000000000b1"
PUBLIC = {"name": "Synthetic Console", "hardware": {"shortname": "SYNTH"}}


def _system() -> dict:
    return json.loads((FIXTURES / "system.json").read_text())


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_the_stub_serves_the_public_payload_to_an_invalid_session(connected, console):
    console.expire_session()
    console.reply("GET", SYSTEM_PATH, _system())

    async with connected._session.get(f"{console.base_url}{SYSTEM_PATH}", headers=connected._auth.headers()) as reply:
        body = await reply.json()

    assert reply.status == 200
    assert "TOKEN" not in reply.cookies
    assert "controllers" not in body.get("apps", {})


async def test_a_read_after_expiry_logs_in_once_and_succeeds(connected, console):
    console.expire_session()
    console.reply("GET", SYSTEM_PATH, _system())

    status = await InnerSpaceSystemManager(connected).get_status()

    assert (status.installed, status.running) == (True, True)
    assert console.logins == 2
    calls = console.calls("GET", SYSTEM_PATH)
    assert [call.headers["Cookie"] for call in calls] == ["TOKEN=session-1", "TOKEN=session-2"]
    # The replaced session was logged out.
    assert [call.headers["Cookie"] for call in console.calls("POST", LOGOUT)] == ["TOKEN=session-1"]


async def test_ensure_app_running_after_expiry_logs_in_once(connected, console):
    console.expire_session()
    console.reply("GET", SYSTEM_PATH, _system())

    await connected.ensure_app_running(OP)

    assert console.logins == 2


async def test_a_public_reply_never_lends_its_session_or_csrf(connected, console):
    """A list-less reply that sets a cookie and a CSRF token is refused before either is adopted."""
    console.reply("GET", SYSTEM_PATH, PUBLIC, headers={"Set-Cookie": "TOKEN=public", "X-Csrf-Token": "public-csrf"})
    console.reply("GET", SYSTEM_PATH, _system())

    await InnerSpaceSystemManager(connected).get_status()

    assert console.logins == 2
    retry = console.calls("GET", SYSTEM_PATH)[1]
    assert (retry.headers["Cookie"], retry.headers["X-CSRF-Token"]) == ("TOKEN=session-2", "csrf-2")
    assert connected._auth.token == "session-2" and connected._auth.csrf == "csrf-2"


async def test_concurrent_reads_after_expiry_log_in_once(connected, console):
    console.expire_session()
    console.hold_401_until(2)
    for _ in range(2):
        console.reply("GET", SYSTEM_PATH, _system())

    results = await asyncio.gather(*(InnerSpaceSystemManager(connected).get_status() for _ in range(2)))

    assert console.held == 2
    assert console.logins == 2
    assert all(status.running for status in results)


async def test_a_write_racing_the_relogin_is_sent_once_on_the_new_session(connected, console):
    """A reader and a write both meet the public payload: one login between them, and the write lands."""
    ready(console)
    console.reply("GET", SYSTEM_PATH, _system())
    console.expire_session()
    console.hold_401_until(2)
    wall = new_wall(WALL_1)

    async def write():
        async def read_back():
            return {WALL_1: stored_shape(console, WALL_1) is not None}

        await ensure_writable(connected, operation=OP)
        body = {"create": [wall], "update": [], "remove": [], "mode": "2D"}
        return await send_write(
            connected, "POST", SHAPE_CHANGE_PATH, body, operation=OP, read_back=read_back, metadata={}
        )

    _status, result = await asyncio.gather(InnerSpaceSystemManager(connected).get_status(), write())

    assert console.logins == 2
    assert (result.success, result.mutation_applied) == (True, True)
    assert len(console.calls("POST", SHAPE_CHANGE_PATH)) == 1
    console.assert_csrf()
    assert stored_shape(console, WALL_1) is not None


async def test_no_app_list_on_the_new_session_is_a_permission_error_once_per_window(connected, console):
    """An account the console answers without the list: one login, then no login inside the window."""
    clock = _Clock()
    connected._clock = clock
    for _ in range(5):
        console.reply("GET", SYSTEM_PATH, PUBLIC)

    with pytest.raises(UniFiPermissionError, match="cannot read the application list") as first:
        await InnerSpaceSystemManager(connected).get_status()
    assert console.logins == 2
    assert len(console.calls("GET", SYSTEM_PATH)) == 2
    assert "not installed" not in str(first.value).lower()

    with pytest.raises(UniFiPermissionError, match="cannot read the application list"):
        await InnerSpaceSystemManager(connected).get_status()
    assert console.logins == 2
    assert len(console.calls("GET", SYSTEM_PATH)) == 3

    clock.now += 61
    with pytest.raises(UniFiPermissionError, match="cannot read the application list"):
        await InnerSpaceSystemManager(connected).get_status()
    assert console.logins == 3


async def test_a_later_read_with_the_list_closes_the_window(connected, console):
    """A reply that carries the list ends the window, so a session expiring right after is renewed once."""
    clock = _Clock()
    connected._clock = clock
    for _ in range(2):
        console.reply("GET", SYSTEM_PATH, PUBLIC)
    with pytest.raises(UniFiPermissionError, match="cannot read the application list"):
        await InnerSpaceSystemManager(connected).get_status()
    assert console.logins == 2

    clock.now += 10
    console.reply("GET", SYSTEM_PATH, _system())
    assert (await InnerSpaceSystemManager(connected).get_status()).running is True

    clock.now += 10
    console.expire_session()
    console.reply("GET", SYSTEM_PATH, _system())
    assert (await InnerSpaceSystemManager(connected).get_status()).running is True
    assert console.logins == 3


async def test_the_window_does_not_block_writes_or_other_reads(connected, console):
    """The app-list window is its own: a later write refusal still gets its ordinary re-login."""
    for _ in range(2):
        console.reply("GET", SYSTEM_PATH, PUBLIC)
    with pytest.raises(UniFiPermissionError):
        await InnerSpaceSystemManager(connected).get_status()

    assert connected._no_access_until == 0.0
    console.reply("GET", SYSTEM_PATH, _system())
    assert (await InnerSpaceSystemManager(connected).get_status()).running is True
    assert console.logins == 2


@pytest.mark.parametrize(
    "controllers",
    [[], [{"name": "network", "isInstalled": True, "isRunning": True}]],
    ids=["empty", "other_apps_only"],
)
async def test_a_list_without_innerspace_is_not_installed_not_refused(connected, console, controllers):
    console.reply("GET", SYSTEM_PATH, {"apps": {"controllers": controllers}})

    status = await InnerSpaceSystemManager(connected).get_status()

    assert (status.installed, status.running) == (False, False)
    assert console.logins == 1
