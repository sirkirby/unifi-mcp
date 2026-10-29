"""Windowed statistics in the stats manager: top clients, v2 DPI, IPS and window parsing."""

import json
import traceback
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiounifi.errors import Forbidden, ResponseError
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiOperationError, UniFiPermissionError
from unifi_core.network.managers import stats_manager as stats_module
from unifi_core.network.managers.stats_manager import StatsManager
from unifi_core.network.time_window import parse_window_bound

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
NOW = 1_790_000_000_000
HOUR = 3_600_000


def _manager(response: Any = None, cached: bool = False) -> tuple[StatsManager, MagicMock]:
    cache: Dict[str, Any] = {}
    connection = MagicMock()
    connection.site = "default"
    if cached:
        connection.get_cached.side_effect = lambda key, timeout=None: cache.get(key)
        connection._update_cache.side_effect = lambda key, value, timeout=None: cache.__setitem__(key, value)
    else:
        connection.get_cached.return_value = None
    connection.request = AsyncMock(return_value=response)
    client_manager = MagicMock()
    client_manager.get_clients = AsyncMock(return_value=[])
    return StatsManager(connection, client_manager), connection


def _path(connection: MagicMock, index: int = -1) -> str:
    return connection.request.call_args_list[index][0][0].path


# --- top clients: report aggregation -------------------------------------------------


@pytest.mark.asyncio
async def test_top_clients_sums_report_over_window() -> None:
    """Ranking comes from the per-client report inside the window, rx counted as upload."""
    manager, connection = _manager(
        [
            {"user": "AA:BB:CC:00:00:01", "rx_bytes": 40, "tx_bytes": 1, "time": 1},
            {"user": "aa:bb:cc:00:00:01", "rx_bytes": 60, "tx_bytes": 1, "time": 2},
            {"user": "aa:bb:cc:00:00:02", "rx_bytes": 5, "tx_bytes": 500, "time": 1},
        ]
    )

    result = await manager.get_top_clients(start_ms=1_000, end_ms=2_000, granularity="5minutes")

    request = connection.request.call_args[0][0]
    assert request.path == "/stat/report/5minutes.user"
    assert request.data["start"] == 1_000 and request.data["end"] == 2_000
    assert "mac" not in request.data and "macs" not in request.data
    assert [r["mac"] for r in result] == ["aa:bb:cc:00:00:02", "aa:bb:cc:00:00:01"]
    uploader = result[1]
    assert uploader["upload_bytes"] == 100 and uploader["download_bytes"] == 2
    assert uploader["rx_bytes"] == 100 and uploader["tx_bytes"] == 2
    assert uploader["total_bytes"] == 102 and uploader["source"] == "report"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sort_by,first",
    [("upload", "aa:bb:cc:00:00:01"), ("download", "aa:bb:cc:00:00:02"), ("total", "aa:bb:cc:00:00:02")],
)
async def test_top_clients_sort_by(sort_by: str, first: str) -> None:
    manager, _ = _manager(
        [
            {"user": "aa:bb:cc:00:00:01", "rx_bytes": 100, "tx_bytes": 0},
            {"user": "aa:bb:cc:00:00:02", "rx_bytes": 5, "tx_bytes": 500},
        ]
    )

    result = await manager.get_top_clients(start_ms=1_000, end_ms=2_000, sort_by=sort_by)

    assert result[0]["mac"] == first


@pytest.mark.asyncio
async def test_top_clients_limit_applies_after_ranking() -> None:
    rows = [{"user": f"aa:bb:cc:00:00:0{i}", "rx_bytes": i, "tx_bytes": 0} for i in range(1, 6)]
    manager, _ = _manager(rows)

    result = await manager.get_top_clients(start_ms=1_000, end_ms=2_000, limit=2)

    assert [r["mac"] for r in result] == ["aa:bb:cc:00:00:05", "aa:bb:cc:00:00:04"]


@pytest.mark.asyncio
async def test_top_clients_cache_holds_full_ranking_for_other_sorts_and_limits() -> None:
    rows = [
        {"user": "aa:bb:cc:00:00:01", "rx_bytes": 100, "tx_bytes": 0},
        {"user": "aa:bb:cc:00:00:02", "rx_bytes": 5, "tx_bytes": 500},
    ]
    manager, connection = _manager(rows, cached=True)

    first = await manager.get_top_clients(start_ms=1_000, end_ms=2_000, limit=1, sort_by="upload")
    second = await manager.get_top_clients(start_ms=1_000, end_ms=2_000, limit=2, sort_by="download")

    assert len([c for c in connection.request.call_args_list if c[0][0].path.startswith("/stat/")]) == 1
    assert [r["mac"] for r in first] == ["aa:bb:cc:00:00:01"]
    assert [r["mac"] for r in second] == ["aa:bb:cc:00:00:02", "aa:bb:cc:00:00:01"]


@pytest.mark.asyncio
async def test_top_clients_parses_malformed_rows_defensively() -> None:
    """A bad counter or row is skipped or read as 0 instead of aborting the ranking."""
    manager, _ = _manager(
        [
            "not-a-row",
            None,
            {"user": None, "rx_bytes": 1},
            {"user": 42, "rx_bytes": 1},
            {"user": "aa:bb:cc:00:00:01", "rx_bytes": "lots", "tx_bytes": {"x": 1}},
            {"user": "aa:bb:cc:00:00:01", "rx_bytes": "7", "tx_bytes": 3.0},
            {"mac": "aa:bb:cc:00:00:02", "rx_bytes": float("nan"), "tx_bytes": 2},
        ]
    )

    result = await manager.get_top_clients(start_ms=1_000, end_ms=2_000)

    by_mac = {r["mac"]: r for r in result}
    assert set(by_mac) == {"aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"}
    assert by_mac["aa:bb:cc:00:00:01"]["upload_bytes"] == 7
    assert by_mac["aa:bb:cc:00:00:01"]["download_bytes"] == 3
    assert by_mac["aa:bb:cc:00:00:02"]["total_bytes"] == 2


@pytest.mark.asyncio
async def test_top_clients_rejects_unknown_sort() -> None:
    manager, _ = _manager([])
    with pytest.raises(ValueError):
        await manager.get_top_clients(sort_by="bytes")


@pytest.mark.asyncio
async def test_top_clients_rejects_inverted_window() -> None:
    manager, _ = _manager([])
    with pytest.raises(ValueError):
        await manager.get_top_clients(start_ms=2_000, end_ms=1_000)


# --- top clients: live-counter fallback ---------------------------------------------

LIVE_CLIENT = {"mac": "aa:bb:cc:00:00:03", "name": "nas", "wired-rx_bytes": 9, "wired-tx_bytes": 1}


@pytest.mark.asyncio
async def test_top_clients_duration_window_falls_back_to_live_counters_marked_as_such() -> None:
    """A controller without the report still answers, but says the numbers are not windowed."""
    manager, _ = _manager([])
    manager._client_manager.get_clients = AsyncMock(return_value=[LIVE_CLIENT])

    result = await manager.get_top_clients()

    assert result[0]["source"] == "live_counters"
    assert result[0]["upload_bytes"] == 9 and result[0]["download_bytes"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [[], {"unexpected": "envelope"}])
@pytest.mark.parametrize("bounds", [{"start_ms": 1_000, "end_ms": 2_000}, {"start_ms": 1_000}, {"end_ms": NOW}])
async def test_top_clients_explicit_window_never_falls_back(response: Any, bounds: Dict[str, int]) -> None:
    """Lifetime counters describe a different period than a pinned window, so the answer is empty."""
    manager, _ = _manager(response)
    manager._client_manager.get_clients = AsyncMock(return_value=[LIVE_CLIENT])

    with patch.object(stats_module, "_now_ms", return_value=NOW):
        result = await manager.get_top_clients(**bounds)

    assert result == []
    manager._client_manager.get_clients.assert_not_awaited()


@pytest.mark.asyncio
async def test_top_clients_live_counter_failure_is_translated() -> None:
    """The fallback read must not carry controller text into the error, like the report path."""
    manager, _ = _manager([])
    manager._client_manager.get_clients = AsyncMock(side_effect=RuntimeError("controller detail aa:bb:cc:00:00:09"))

    with pytest.raises(stats_module.RequestError) as excinfo:
        await manager.get_top_clients()

    assert str(excinfo.value) == "Top clients live counter read failed (RuntimeError)."
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__


# --- top clients: automatic granularity ---------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "age_ms,expected",
    [
        (1 * HOUR, "5minutes"),
        (12 * HOUR, "5minutes"),
        (3 * 24 * HOUR, "hourly"),
        (7 * 24 * HOUR, "hourly"),
        (30 * 24 * HOUR, "daily"),
    ],
)
async def test_top_clients_auto_granularity_follows_window_age(age_ms: int, expected: str) -> None:
    manager, connection = _manager([])
    with patch.object(stats_module, "_now_ms", return_value=NOW):
        await manager.get_top_clients(start_ms=NOW - age_ms, end_ms=NOW)
    assert _path(connection) == f"/stat/report/{expected}.user"


@pytest.mark.asyncio
async def test_weekly_duration_granularity_does_not_depend_on_timing() -> None:
    """duration_hours=168 sits exactly on the hourly threshold; now is read once, so it stays hourly."""
    clock = iter(range(NOW, NOW + 1_000))
    manager, connection = _manager([])
    with patch.object(stats_module, "_now_ms", side_effect=lambda: next(clock)):
        await manager.get_top_clients(duration_hours=168)
    request = connection.request.call_args[0][0]
    assert request.path == "/stat/report/hourly.user"
    assert request.data["end"] - request.data["start"] == 168 * HOUR


# --- client stats cache ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_stats_absolute_window() -> None:
    manager, connection = _manager([])

    await manager.get_client_stats("aa:bb:cc:00:00:01", start_ms=1_000, end_ms=5_000)

    request = connection.request.call_args[0][0]
    assert request.data["start"] == 1_000 and request.data["end"] == 5_000


@pytest.mark.asyncio
async def test_client_stats_end_only_cache_key_includes_duration() -> None:
    """Same end, different duration: the second call must not be served the first call's rows."""
    manager, connection = _manager([{"time": 1}], cached=True)

    await manager.get_client_stats("aa:bb:cc:00:00:01", duration_hours=1, end_ms=NOW)
    await manager.get_client_stats("aa:bb:cc:00:00:01", duration_hours=168, end_ms=NOW)
    await manager.get_client_stats("aa:bb:cc:00:00:01", duration_hours=1, end_ms=NOW)

    reports = [call[0][0] for call in connection.request.call_args_list if call[0][0].path.startswith("/stat/")]
    assert [request.data["start"] for request in reports] == [NOW - HOUR, NOW - 168 * HOUR]


# --- v2 DPI ---------------------------------------------------------------------------

V2_CLIENT_TRAFFIC = {
    "client_usage_by_app": [
        {
            "client": {"mac": "AA:BB:CC:00:00:01"},
            "usage_by_app": [
                {"application": 234, "category": 13, "bytes_transmitted": 70, "bytes_received": 1, "total_bytes": 71},
                {"application": 10, "category": 4, "bytes_transmitted": 1, "bytes_received": 200, "total_bytes": 201},
                {"application": 11, "category": 13, "bytes_transmitted": 5, "bytes_received": 4, "total_bytes": 9},
            ],
        },
        {"client": {"mac": "aa:bb:cc:00:00:02"}, "usage_by_app": [{"application": 1, "total_bytes": 999}]},
    ],
    "total_usage_by_app": [],
}


@pytest.mark.asyncio
async def test_client_dpi_uses_v2_window_and_filters_client() -> None:
    manager, connection = _manager(V2_CLIENT_TRAFFIC)

    result = await manager.get_client_dpi_traffic("aa:bb:cc:00:00:01", start_ms=1_000, end_ms=2_000)

    assert _path(connection).startswith("/traffic?start=1000&end=2000")
    assert [r["application"] for r in result] == [10, 234, 11]
    assert result[0]["upload_bytes"] == 1 and result[0]["download_bytes"] == 200
    assert result[1]["upload_bytes"] == 70 and result[1]["download_bytes"] == 1
    assert connection.request.await_count == 1


@pytest.mark.asyncio
async def test_client_dpi_by_category_folds_apps() -> None:
    manager, _ = _manager(V2_CLIENT_TRAFFIC)

    result = await manager.get_client_dpi_traffic("aa:bb:cc:00:00:01", by="by_cat")

    assert result == [
        {
            "category": 4,
            "bytes_transmitted": 1,
            "bytes_received": 200,
            "total_bytes": 201,
            "upload_bytes": 1,
            "download_bytes": 200,
        },
        {
            "category": 13,
            "bytes_transmitted": 75,
            "bytes_received": 5,
            "total_bytes": 80,
            "upload_bytes": 75,
            "download_bytes": 5,
        },
    ]


@pytest.mark.asyncio
async def test_client_dpi_v2_list_envelope_is_unwrapped() -> None:
    manager, connection = _manager([V2_CLIENT_TRAFFIC])

    result = await manager.get_client_dpi_traffic("aa:bb:cc:00:00:01")

    assert len(result) == 3
    assert connection.request.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_site_dpi_traffic", "get_client_dpi_traffic"])
async def test_empty_but_valid_v2_aggregate_skips_legacy(method: str) -> None:
    manager, connection = _manager({"total_usage_by_app": [], "client_usage_by_app": []})
    args = ("aa:bb:cc:00:00:01",) if method == "get_client_dpi_traffic" else ()

    assert await getattr(manager, method)(*args) == []

    assert connection.request.await_count == 1
    assert _path(connection).startswith("/traffic?")


@pytest.mark.asyncio
async def test_site_dpi_uses_v2_totals() -> None:
    manager, _ = _manager(
        {
            "total_usage_by_app": [
                {"application": 7, "category": 3, "bytes_transmitted": 1, "bytes_received": 1, "total_bytes": 2},
                {"application": 65535, "category": 255, "bytes_transmitted": 9, "total_bytes": 9},
            ]
        }
    )

    result = await manager.get_site_dpi_traffic(start_ms=1_000, end_ms=2_000)

    assert result[0]["application"] == 65535 and result[0]["upload_bytes"] == 9
    assert result[0]["download_bytes"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,legacy", [("get_site_dpi_traffic", "/stat/sitedpi"), ("get_client_dpi_traffic", "/stat/stadpi")]
)
async def test_dpi_falls_back_to_legacy_when_v2_missing(method: str, legacy: str) -> None:
    manager, connection = _manager()
    connection.request.side_effect = [RuntimeError("404"), [{"app": 2}]]
    args = ("aa:bb:cc:00:00:01",) if method == "get_client_dpi_traffic" else ()

    result = await getattr(manager, method)(*args)

    assert result == [{"app": 2}]
    assert _path(connection, 1) == legacy
    connection._update_cache.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_site_dpi_traffic", "get_client_dpi_traffic"])
async def test_transient_v2_failure_is_not_cached_as_no_traffic(method: str) -> None:
    """v2 fails once, legacy answers [] (as it always does on 10.x): the next call must retry v2."""
    manager, connection = _manager(cached=True)
    connection.request.side_effect = [
        RuntimeError("503"),
        [],
        V2_CLIENT_TRAFFIC | {"total_usage_by_app": [{"total_bytes": 5}]},
    ]
    args = ("aa:bb:cc:00:00:01",) if method == "get_client_dpi_traffic" else ()

    assert await getattr(manager, method)(*args) == []
    second = await getattr(manager, method)(*args)

    assert second
    assert connection.request.await_count == 3
    assert _path(connection).startswith("/traffic?")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_site_dpi_traffic", "get_client_dpi_traffic"])
async def test_legacy_controller_empty_answer_is_still_cached(method: str) -> None:
    """Without a v2 failure (v2 present but without the aggregate), an empty legacy answer is real."""
    manager, connection = _manager(cached=True)
    connection.request.side_effect = [{"other": 1}, []]
    args = ("aa:bb:cc:00:00:01",) if method == "get_client_dpi_traffic" else ()

    assert await getattr(manager, method)(*args) == []
    assert await getattr(manager, method)(*args) == []

    assert connection.request.await_count == 2


# --- IPS fallback ---------------------------------------------------------------------


def _system_log_fixture() -> Dict[str, Any]:
    return json.loads((FIXTURES / "system_log_events_response.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("envelope", ["dict", "list", "logs", "logs-list"])
async def test_ips_fallback_returns_only_intrusion_prevention_rows(envelope: str) -> None:
    """The SECURITY category also holds firewall blocks; with limit=1 the threat must still win."""
    page = _system_log_fixture()
    if envelope.startswith("logs"):
        page = {"logs": page["data"]}
    manager, connection = _manager()
    connection.request.side_effect = [[], [page] if envelope in {"list", "logs-list"} else page]

    result = await manager.get_ips_events(limit=1)

    assert [row["subcategory"] for row in result] == ["SECURITY_INTRUSION_PREVENTION"]
    v2_request = connection.request.call_args_list[1][0][0]
    assert v2_request.path == "/system-log/all"
    assert v2_request.data["categories"] == ["SECURITY"]
    assert v2_request.data["subcategories"] == ["SECURITY_INTRUSION_PREVENTION"]


@pytest.mark.asyncio
async def test_ips_fallback_reads_further_pages_when_firewall_rows_crowd_out_threats() -> None:
    firewall = {"category": "SECURITY", "subcategory": "SECURITY_FIREWALL"}
    threat = {"category": "SECURITY", "subcategory": "SECURITY_INTRUSION_PREVENTION", "id": "t1"}
    full_page = {"data": [firewall] * stats_module._IPS_V2_PAGE_SIZE}
    manager, connection = _manager()
    connection.request.side_effect = [[], full_page, {"data": [firewall, threat]}]

    result = await manager.get_ips_events(limit=5)

    assert result == [threat]
    pages = [call[0][0].data["pageNumber"] for call in connection.request.call_args_list[1:]]
    assert pages == [0, 1]


@pytest.mark.asyncio
async def test_ips_fallback_page_reads_are_bounded() -> None:
    firewall = {"category": "SECURITY", "subcategory": "SECURITY_FIREWALL"}
    manager, connection = _manager()
    connection.request.side_effect = [[]] + [{"data": [firewall] * stats_module._IPS_V2_PAGE_SIZE}] * 50

    assert await manager.get_ips_events(limit=5) == []
    assert connection.request.await_count == 1 + stats_module._IPS_V2_MAX_PAGES


@pytest.mark.asyncio
async def test_ips_fallback_stopped_by_page_bound_is_not_cached() -> None:
    """Threats past the page bound are unread, so the partial answer must not stand for the window."""
    firewall = {"category": "SECURITY", "subcategory": "SECURITY_FIREWALL"}
    full_page = {"data": [firewall] * stats_module._IPS_V2_PAGE_SIZE}
    manager, connection = _manager(cached=True)
    connection.request.side_effect = ([[]] + [full_page] * stats_module._IPS_V2_MAX_PAGES) * 2

    assert await manager.get_ips_events(limit=5) == []
    assert await manager.get_ips_events(limit=5) == []
    assert connection.request.await_count == 2 * (1 + stats_module._IPS_V2_MAX_PAGES)


@pytest.mark.asyncio
async def test_ips_fallback_complete_read_is_cached() -> None:
    threat = {"category": "SECURITY", "subcategory": "SECURITY_INTRUSION_PREVENTION", "id": "t1"}
    manager, connection = _manager(cached=True)
    connection.request.side_effect = [[], {"data": [threat]}]

    assert await manager.get_ips_events(limit=5) == [threat]
    assert await manager.get_ips_events(limit=5) == [threat]
    assert connection.request.await_count == 2


@pytest.mark.asyncio
async def test_ips_fallback_drops_rows_repeated_across_pages() -> None:
    """A new event shifts rows between page reads, so the last row of one page can open the next."""
    firewall = {"category": "SECURITY", "subcategory": "SECURITY_FIREWALL"}
    threat = {"category": "SECURITY", "subcategory": "SECURITY_INTRUSION_PREVENTION", "id": "t1"}
    full_page = {"data": [firewall] * (stats_module._IPS_V2_PAGE_SIZE - 1) + [threat]}
    manager, connection = _manager()
    connection.request.side_effect = [[], full_page, {"data": [threat]}]

    assert await manager.get_ips_events(limit=5) == [threat]


@pytest.mark.asyncio
async def test_ips_fallback_junk_row_does_not_end_paging_early() -> None:
    firewall = {"category": "SECURITY", "subcategory": "SECURITY_FIREWALL"}
    threat = {"category": "SECURITY", "subcategory": "SECURITY_INTRUSION_PREVENTION", "id": "t2"}
    page = {"data": [firewall] * (stats_module._IPS_V2_PAGE_SIZE - 1) + ["junk"]}
    manager, connection = _manager()
    connection.request.side_effect = [[], page, {"data": [threat]}]

    assert await manager.get_ips_events(limit=5) == [threat]


@pytest.mark.asyncio
async def test_ips_fallback_unreadable_row_beside_readable_rows_is_skipped() -> None:
    threat = {"category": "SECURITY", "subcategory": "SECURITY_INTRUSION_PREVENTION", "id": "t3"}
    manager, connection = _manager()
    connection.request.side_effect = [[], {"data": [{"unexpected": []}, threat]}]

    assert await manager.get_ips_events(limit=5) == [threat]


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [[], {"unexpected": "legacy envelope"}])
@pytest.mark.parametrize(
    "error,expected,status",
    [
        (Forbidden("PRIVATE_CONTROLLER_TEXT"), UniFiPermissionError, None),
        (TimeoutError("PRIVATE_CONTROLLER_TEXT"), TimeoutError, None),
        (ResponseError("Call https://fixture.invalid received 403 PRIVATE_CONTROLLER_TEXT"), UniFiOperationError, 403),
        (ResponseError("Call https://fixture.invalid received 404 PRIVATE_CONTROLLER_TEXT"), UniFiOperationError, 404),
        (ResponseError("Call https://fixture.invalid received 503 PRIVATE_CONTROLLER_TEXT"), UniFiOperationError, 503),
    ],
)
async def test_ips_fallback_failure_is_not_an_empty_success(legacy, error, expected, status, caplog) -> None:
    manager, connection = _manager()
    connection.request.side_effect = [legacy, error]

    with pytest.raises(expected, match="IPS events") as caught:
        await manager.get_ips_events(limit=1)

    assert caught.value.status == status
    assert "PRIVATE_CONTROLLER_TEXT" not in str(caught.value)
    assert "PRIVATE_CONTROLLER_TEXT" not in caplog.text
    connection._update_cache.assert_not_called()
    assert connection.request.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page",
    [
        None,
        42,
        {"unexpected": []},
        {"data": None},
        [{"data": "not rows"}],
        [{"unexpected": []}],
        [{"total_element_count": 1}],
        {"totalElementCount": 1},
        {"total_element_count": False},
        [{"totalElementCount": False}],
        {"total_element_count": "0"},
        [{"total_element_count": -1}],
        {"total_page_count": 0},
        [{"totalPageCount": 0}],
        {"data": None, "total_element_count": 0},
        [{"logs": None, "totalElementCount": 0}],
        [{"total_element_count": 0}, {"total_element_count": 0}],
        [{"totalElementCount": 0}, {"category": "SECURITY"}],
        {"data": [{"unexpected": []}]},
        ["not a log row"],
        [{"data": []}, {"data": []}],
    ],
)
async def test_ips_fallback_malformed_page_is_not_empty(page) -> None:
    manager, connection = _manager()
    connection.request.side_effect = [[], page]

    with pytest.raises(UniFiMalformedResponseError):
        await manager.get_ips_events(limit=1)

    connection._update_cache.assert_not_called()


@pytest.mark.asyncio
async def test_ips_malformed_fallback_suppresses_private_legacy_exception_context(caplog) -> None:
    manager, connection = _manager()
    connection.request.side_effect = [RuntimeError("PRIVATE_LEGACY_TEXT"), [{"data": None}]]

    with pytest.raises(UniFiMalformedResponseError) as caught:
        await manager.get_ips_events(limit=1)

    assert "PRIVATE_LEGACY_TEXT" not in "".join(traceback.format_exception(caught.value))
    assert "PRIVATE_LEGACY_TEXT" not in caplog.text
    connection._update_cache.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page",
    [
        [],
        {"data": []},
        {"logs": []},
        [{"data": []}],
        [{"logs": []}],
        {"total_element_count": 0},
        [{"total_element_count": 0}],
        {"total_element_count": 0, "total_page_count": 0},
        [{"total_element_count": 0, "total_page_count": 0}],
        {"totalElementCount": 0},
        [{"totalElementCount": 0}],
        {"totalElementCount": 0, "totalPageCount": 0},
        [{"totalElementCount": 0, "totalPageCount": 0}],
    ],
)
async def test_ips_fallback_valid_empty_page_remains_cacheable(page) -> None:
    manager, connection = _manager(cached=True)
    connection.request.side_effect = [[], page]

    assert await manager.get_ips_events(limit=1) == []
    assert await manager.get_ips_events(limit=1) == []
    assert connection.request.await_count == 2


# --- window bound parsing -------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (1_790_930_100, 1_790_930_100_000),
        (1_790_930_100_000, 1_790_930_100_000),
        ("1790930100", 1_790_930_100_000),
        ("1790930100000", 1_790_930_100_000),
        ("2026-10-02T06:35:00Z", 1_790_922_900_000),
        ("2026-10-02T02:35:00-04:00", 1_790_922_900_000),
        (" 2026-10-02T06:35:00+00:00 ", 1_790_922_900_000),
    ],
)
def test_parse_window_bound_accepts(value: Any, expected: Any) -> None:
    assert parse_window_bound(value) == expected


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_parse_window_bound_rejects_blank(value: str) -> None:
    with pytest.raises(ValueError, match="Empty time bound"):
        parse_window_bound(value)


@pytest.mark.parametrize("value", ["2026-10-02T06:35:00", "2026-10-02"])
def test_parse_window_bound_rejects_naive_iso(value: str) -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        parse_window_bound(value)


@pytest.mark.parametrize("value", ["last tuesday", True])
def test_parse_window_bound_rejects_garbage(value: Any) -> None:
    with pytest.raises(ValueError):
        parse_window_bound(value)
