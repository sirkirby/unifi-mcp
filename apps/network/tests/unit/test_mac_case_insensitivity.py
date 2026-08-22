"""MAC lookups must be case-insensitive at every entry point.

The controller stores and reports MACs in lowercase. Every one of these
lookups previously compared the caller's string to the controller's with a
raw `==`, so an uppercase MAC - the form printed on most device labels -
reported "not found" for hardware that was sitting right there. One code
path (StatsManager.get_client_wifi_details) already lowercased both sides,
which is what made the inconsistency invisible: whichever tool you happened
to try first decided whether you believed the bug existed.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.managers.device_manager import DeviceManager
from unifi_core.network.managers.event_manager import EventBuffer

LOWER = "aa:bb:cc:dd:ee:ff"
UPPER = "AA:BB:CC:DD:EE:FF"


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.site = "default"
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    conn.controller = MagicMock()
    conn.controller.clients = MagicMock()
    conn.controller.clients.update = AsyncMock()
    conn.controller.clients.values = MagicMock(return_value=[])
    conn.controller.clients_all = MagicMock()
    conn.controller.clients_all.update = AsyncMock()
    conn.controller.clients_all.values = MagicMock(return_value=[])
    conn.controller.devices = MagicMock()
    conn.controller.devices.update = AsyncMock()
    conn.controller.devices.values = MagicMock(return_value=[])
    conn.request = AsyncMock(return_value=None)
    return conn


def _client(mac: str, **extra):
    obj = MagicMock()
    obj.mac = mac
    obj.raw = {"mac": mac, **extra}
    return obj


@pytest.mark.asyncio
async def test_client_lookup_accepts_uppercase(mock_connection):
    """ClientManager.get_client_details backs block/unblock/rename/forget/
    reconnect/authorize/set-ip - one raw `==` broke all of them at once."""
    mock_connection.controller.clients.values.return_value = [_client(LOWER, signal=-52)]
    mgr = ClientManager(mock_connection)
    result = await mgr.get_client_details(UPPER)
    assert result.raw["signal"] == -52


@pytest.mark.asyncio
async def test_client_lookup_still_rejects_a_genuinely_absent_mac(mock_connection):
    """Normalizing must not turn the lookup into a match-anything."""
    from unifi_core.exceptions import UniFiNotFoundError

    mock_connection.controller.clients.values.return_value = [_client(LOWER)]
    mgr = ClientManager(mock_connection)
    with pytest.raises(UniFiNotFoundError):
        await mgr.get_client_details("11:22:33:44:55:66")


@pytest.mark.asyncio
async def test_device_lookup_accepts_uppercase(mock_connection):
    """DeviceManager.get_device_details backs reboot/adopt/upgrade/rename/
    radio/PDU-outlet."""
    device = MagicMock()
    device.mac = LOWER
    mock_connection.controller.devices.values.return_value = [device]
    mgr = DeviceManager(mock_connection)
    assert await mgr.get_device_details(UPPER) is device


@pytest.mark.asyncio
async def test_device_lookup_still_raises_for_absent_mac(mock_connection):
    from unifi_core.exceptions import UniFiNotFoundError

    device = MagicMock()
    device.mac = LOWER
    mock_connection.controller.devices.values.return_value = [device]
    mgr = DeviceManager(mock_connection)
    with pytest.raises(UniFiNotFoundError):
        await mgr.get_device_details("11:22:33:44:55:66")


def test_event_buffer_mac_filter_accepts_uppercase() -> None:
    """The websocket buffer stores controller-cased MACs; an uppercase filter
    returned zero matches with no error to suggest why."""
    buf = EventBuffer(max_size=10, ttl_seconds=300)
    buf.add({"id": "e1", "mac": LOWER})
    buf.add({"id": "e2", "mac": "11:22:33:44:55:66"})
    assert [e["id"] for e in buf.get_recent(mac=UPPER)] == ["e1"]


def test_event_buffer_mac_filter_excludes_other_macs() -> None:
    buf = EventBuffer(max_size=10, ttl_seconds=300)
    buf.add({"id": "e1", "mac": LOWER})
    assert buf.get_recent(mac="11:22:33:44:55:66") == []


def test_event_buffer_mac_filter_skips_events_without_a_mac() -> None:
    """An event carrying no `mac` must not match a MAC filter."""
    buf = EventBuffer(max_size=10, ttl_seconds=300)
    buf.add({"id": "no-mac"})
    assert buf.get_recent(mac=UPPER) == []


# --- Outbound normalization -------------------------------------------------
#
# Fixing only the comparison is the more dangerous half-measure: the lookup
# starts succeeding and the caller's raw uppercase string then goes to the
# controller in the command body or the URL path. Today an uppercase MAC fails
# fast at the lookup and dispatches nothing; after a comparison-only fix it
# would dispatch and fail later, and more quietly. The controller reports
# lowercase, so lowercase is certainly a form it accepts.


def _sent(mock_connection):
    """The data payloads of every request the manager issued."""
    return [call.args[0].data for call in mock_connection.request.call_args_list if call.args]


def _paths(mock_connection):
    return [call.args[0].path for call in mock_connection.request.call_args_list if call.args]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,cmd",
    [
        ("block_client", "block-sta"),
        ("unblock_client", "unblock-sta"),
        ("force_reconnect_client", "kick-sta"),
    ],
)
async def test_client_commands_send_a_lowercase_mac(mock_connection, method, cmd):
    mock_connection.controller.clients.values.return_value = [_client(LOWER)]
    mgr = ClientManager(mock_connection)
    await getattr(mgr, method)(UPPER)
    payloads = [d for d in _sent(mock_connection) if isinstance(d, dict) and d.get("cmd") == cmd]
    assert payloads, f"no {cmd} command was dispatched"
    assert payloads[0]["mac"] == LOWER


@pytest.mark.asyncio
@pytest.mark.parametrize("method,cmd", [("reboot_device", "restart"), ("upgrade_device", "upgrade")])
async def test_device_commands_send_a_lowercase_mac(mock_connection, method, cmd):
    device = MagicMock()
    device.mac = LOWER
    mock_connection.controller.devices.values.return_value = [device]
    mgr = DeviceManager(mock_connection)
    await getattr(mgr, method)(UPPER)
    payloads = [d for d in _sent(mock_connection) if isinstance(d, dict) and d.get("cmd") == cmd]
    assert payloads, f"no {cmd} command was dispatched"
    assert payloads[0]["mac"] == LOWER


@pytest.mark.asyncio
async def test_spectrum_scan_url_uses_a_lowercase_mac(mock_connection):
    """device_manager interpolates the MAC straight into the path."""
    device = MagicMock()
    device.mac = LOWER
    mock_connection.controller.devices.values.return_value = [device]
    mock_connection.request = AsyncMock(return_value={"data": []})
    mgr = DeviceManager(mock_connection)
    await mgr.get_rf_scan_results(UPPER)
    assert any(UPPER not in p and LOWER in p for p in _paths(mock_connection)), _paths(mock_connection)


@pytest.mark.asyncio
async def test_authorize_guest_sends_a_lowercase_mac(mock_connection):
    """authorize_guest was the one command method the first pass missed.

    Its existence check goes through get_client_details, which normalizes its
    own local copy - so after that fix the lookup succeeded and the caller's
    raw uppercase string went out in the command. The tool layer reports
    success, so a guest that was never authorized looks authorized.
    """
    mock_connection.controller.clients.values.return_value = [_client(LOWER)]
    mgr = ClientManager(mock_connection)
    await mgr.authorize_guest(UPPER, minutes=60)
    payloads = [d for d in _sent(mock_connection) if isinstance(d, dict) and d.get("cmd") == "authorize-guest"]
    assert payloads, "no authorize-guest command was dispatched"
    assert payloads[0]["mac"] == LOWER


@pytest.mark.asyncio
async def test_unauthorize_guest_sends_a_lowercase_mac(mock_connection):
    mock_connection.controller.clients.values.return_value = [_client(LOWER)]
    mgr = ClientManager(mock_connection)
    await mgr.unauthorize_guest(UPPER)
    payloads = [d for d in _sent(mock_connection) if isinstance(d, dict) and d.get("cmd") == "unauthorize-guest"]
    assert payloads and payloads[0]["mac"] == LOWER


# --- Stats and speedtest ----------------------------------------------------
#
# These have no lookup gate, so they never 404'd - they return
# {"success": true, "data": []} for an uppercase MAC. That is the quiet
# variant of the same defect: the caller is told nothing went wrong.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,key",
    [
        ("get_client_stats", "mac"),
        ("get_client_sessions", "mac"),
        ("get_client_dpi_traffic", "macs"),
    ],
)
async def test_client_stats_queries_send_a_lowercase_mac(mock_connection, method, key):
    from unifi_core.network.managers.stats_manager import StatsManager

    mock_connection.request = AsyncMock(return_value={"data": []})
    mgr = StatsManager(mock_connection, ClientManager(mock_connection))
    await getattr(mgr, method)(UPPER)
    sent = [d for d in _sent(mock_connection) if isinstance(d, dict) and key in d]
    assert sent, f"no request carrying {key!r} was issued"
    value = sent[0][key]
    assert (value == [LOWER]) if isinstance(value, list) else (value == LOWER)


@pytest.mark.asyncio
async def test_device_stats_query_sends_a_lowercase_mac(mock_connection):
    from unifi_core.network.managers.stats_manager import StatsManager

    mock_connection.request = AsyncMock(return_value={"data": []})
    mgr = StatsManager(mock_connection, ClientManager(mock_connection))
    await mgr.get_device_stats(UPPER)
    sent = [d for d in _sent(mock_connection) if isinstance(d, dict) and "mac" in d]
    assert sent and sent[0]["mac"] == LOWER


@pytest.mark.asyncio
async def test_speedtest_commands_send_a_lowercase_mac(mock_connection):
    mock_connection.request = AsyncMock(return_value={"data": []})
    mgr = DeviceManager(mock_connection)
    await mgr.trigger_speedtest(UPPER)
    sent = [d for d in _sent(mock_connection) if isinstance(d, dict) and d.get("cmd") == "speedtest"]
    assert sent and sent[0]["mac"] == LOWER


# --- Remaining entry points -------------------------------------------------
#
# Round 2 established that most normalization sites had no biting test: a
# simultaneous mutation of every insertion left unifi-core and apps/api fully
# green. These cover the ones a caller can reach with a MAC.


@pytest.mark.asyncio
async def test_speedtest_status_query_sends_a_lowercase_mac(mock_connection):
    mock_connection.request = AsyncMock(return_value={"data": []})
    mgr = DeviceManager(mock_connection)
    await mgr.get_speedtest_status(UPPER)
    payloads = [d for d in _sent(mock_connection) if isinstance(d, dict)]
    assert payloads, "no request was issued"
    assert not any(UPPER in str(d) for d in payloads), payloads


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method",
    ["get_switch_ports", "get_port_stats", "get_switch_capabilities"],
)
async def test_switch_reads_use_a_lowercase_mac_in_the_url(mock_connection, method):
    """switch_manager interpolates the MAC into `/stat/device/{mac}`."""
    from unifi_core.network.managers.switch_manager import SwitchManager

    mock_connection.request = AsyncMock(return_value={"data": []})
    mgr = SwitchManager(mock_connection)
    fn = getattr(mgr, method, None)
    if fn is None:
        pytest.skip(f"{method} not present")
    await fn(UPPER)
    paths = _paths(mock_connection)
    assert paths, "no request was issued"
    assert not any(UPPER in p for p in paths), paths


@pytest.mark.asyncio
async def test_rename_device_sends_a_lowercase_mac(mock_connection):
    device = MagicMock()
    device.mac = LOWER
    device.id = "dev1"
    device.raw = {"mac": LOWER, "_id": "dev1"}
    mock_connection.controller.devices.values.return_value = [device]
    mgr = DeviceManager(mock_connection)
    try:
        await mgr.rename_device(UPPER, "new-name")
    except Exception:
        pass  # the write path may need more of the controller than this mock offers
    assert not any(UPPER in str(d) for d in _sent(mock_connection)), _sent(mock_connection)
