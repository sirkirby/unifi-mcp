"""The InnerSpace app status manager: parsing, malformed bodies and refused sessions."""

import json
from pathlib import Path

import pytest
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiPermissionError
from unifi_core.innerspace.managers.connection_manager import SYSTEM_PATH, InnerSpaceUnavailableError
from unifi_core.innerspace.managers.system_manager import InnerSpaceSystemManager

from tests.innerspace.conftest import ACCESS_DENIED

FIXTURES = Path(__file__).parent / "fixtures"


def _system() -> dict:
    return json.loads((FIXTURES / "system.json").read_text())


async def test_get_status_from_fixture(connected, console):
    console.reply("GET", SYSTEM_PATH, _system())

    status = await InnerSpaceSystemManager(connected).get_status()

    assert (status.installed, status.running, status.version, status.update_available) == (True, True, "1.4.3", None)


async def test_get_status_reports_update_available(connected, console):
    system = _system()
    system["apps"]["controllers"][0]["updateAvailable"] = "1.5.0"
    console.reply("GET", SYSTEM_PATH, system)

    status = await InnerSpaceSystemManager(connected).get_status()

    assert status.update_available == "1.5.0"


async def test_entry_absent_is_not_installed(connected, console):
    system = _system()
    del system["apps"]["controllers"][0]
    console.reply("GET", SYSTEM_PATH, system)

    status = await InnerSpaceSystemManager(connected).get_status()

    assert (status.installed, status.running, status.version) == (False, False, None)


@pytest.mark.parametrize("field", ["isInstalled", "isRunning"])
@pytest.mark.parametrize("value", ["absent", None, "true", 1])
async def test_entry_without_boolean_flags_is_malformed(connected, console, field, value):
    system = _system()
    entry = system["apps"]["controllers"][0]
    if value == "absent":
        del entry[field]
    else:
        entry[field] = value
    console.reply("GET", SYSTEM_PATH, system)

    with pytest.raises(UniFiMalformedResponseError):
        await InnerSpaceSystemManager(connected).get_status()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"apps": {}},
        {"apps": {"controllers": None}},
        {"apps": {"controllers": {}}},
        {"apps": {"controllers": "innerspace"}},
        {"apps": []},
        [],
    ],
)
async def test_a_reply_without_the_app_list_is_a_refused_session(connected, console, payload):
    """The public payload a refused session gets: one re-login, and the same on the new session is a permission
    error that never says "not installed"."""
    console.reply("GET", SYSTEM_PATH, payload)
    console.reply("GET", SYSTEM_PATH, payload)

    with pytest.raises(UniFiPermissionError, match="cannot read the application list") as refused:
        await InnerSpaceSystemManager(connected).get_status()

    assert console.logins == 2
    assert len(console.calls("GET", SYSTEM_PATH)) == 2
    assert "not installed" not in str(refused.value).lower()


async def test_non_json_body_is_malformed(connected, console):
    console.reply("GET", SYSTEM_PATH, body_bytes=b"<html>not json</html>")

    with pytest.raises(UniFiMalformedResponseError):
        await InnerSpaceSystemManager(connected).get_status()


async def test_system_auth_errors(connected, console):
    clock = [1000.0]
    connected._clock = lambda: clock[0]
    # 403 errors.api.access: one re-login, then the same refusal is a permission error.
    console.reply("GET", SYSTEM_PATH, ACCESS_DENIED, status=403)
    console.reply("GET", SYSTEM_PATH, ACCESS_DENIED, status=403)
    with pytest.raises(UniFiPermissionError) as refused:
        await InnerSpaceSystemManager(connected).get_status()
    assert console.logins == 2
    assert len(console.calls("GET", SYSTEM_PATH)) == 2
    assert "not installed" not in str(refused.value).lower()

    # 401 right after a fresh login: the session is dropped and the app is unavailable.
    # Past the no-access window, so the 403 leads to one more login.
    clock[0] += 61
    console.reply("GET", SYSTEM_PATH, ACCESS_DENIED, status=403)
    console.reply("GET", SYSTEM_PATH, status=401)
    with pytest.raises(InnerSpaceUnavailableError) as unavailable:
        await InnerSpaceSystemManager(connected).get_status()
    assert "not installed" not in str(unavailable.value).lower()
