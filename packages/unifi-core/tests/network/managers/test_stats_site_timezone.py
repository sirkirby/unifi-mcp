"""Network 11 daily and monthly stats rows begin at the site's local midnight, as legacy reports do."""

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from aiounifi.errors import RequestError
from unifi_core.network import stats_series
from unifi_core.network.managers.stats_manager import StatsManager

CHICAGO = ZoneInfo("America/Chicago")
SITE = "11111111-2222-3333-4444-555555555555"
FIVE_MINUTES = 300_000


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _utc(*args: int) -> int:
    return _ms(datetime(*args, tzinfo=timezone.utc))


def _local(*args: int) -> int:
    return _ms(datetime(*args, tzinfo=CHICAGO))


def _fold(points, granularity: str, tz=CHICAGO) -> Dict[int, Dict[str, Any]]:
    stamps = [p["timestamp"] for p in points]
    return stats_series.legacy_rows(
        [{"series": points}],
        {"rxBytes": "rx_bytes", "wifiTxRetryPackets": "tx_retries"},
        start_ms=min(stamps),
        end_ms=max(stamps) + 1,
        granularity=granularity,
        tz=tz,
    )


def test_daily_buckets_split_at_local_midnight_not_utc_midnight():
    # 23:55 and 00:00 Chicago time on either side of the local day boundary; both are 2026-11-10 in UTC.
    rows = _fold(
        [
            {"timestamp": _utc(2026, 11, 10, 5, 55), "rxBytes": 1},
            {"timestamp": _utc(2026, 11, 10, 6, 0), "rxBytes": 2},
        ],
        "daily",
    )

    assert rows == {
        _local(2026, 11, 9): {"rx_bytes": 1},
        _local(2026, 11, 10): {"rx_bytes": 2},
    }


def test_daily_buckets_follow_the_daylight_saving_change():
    # 2026-11-01 is 25 hours long in Chicago: 23:30 local that night is 05:30 UTC the next day.
    rows = _fold(
        [
            {"timestamp": _utc(2026, 11, 1, 5, 0), "rxBytes": 1},
            {"timestamp": _utc(2026, 11, 2, 5, 30), "rxBytes": 2},
            {"timestamp": _utc(2026, 11, 2, 6, 0), "rxBytes": 4},
        ],
        "daily",
    )

    assert rows == {_local(2026, 11, 1): {"rx_bytes": 3}, _local(2026, 11, 2): {"rx_bytes": 4}}
    assert _local(2026, 11, 2) - _local(2026, 11, 1) == 25 * 3_600_000


def test_monthly_buckets_start_on_the_local_first_of_the_month():
    # 21:00 Chicago time on 31 October is already 1 November in UTC.
    rows = _fold([{"timestamp": _utc(2026, 11, 1, 2, 0), "rxBytes": 7}], "monthly")

    assert rows == {_local(2026, 10, 1): {"rx_bytes": 7}}


def test_utc_remains_the_default_zone():
    rows = _fold([{"timestamp": _utc(2026, 11, 10, 5, 55), "rxBytes": 1}], "daily", tz=timezone.utc)

    assert list(rows) == [_utc(2026, 11, 10)]


def test_byte_and_packet_sums_are_whole_numbers():
    rows = _fold(
        [
            {"timestamp": _utc(2026, 11, 10, 7, 0), "rxBytes": 322129485.26564556, "wifiTxRetryPackets": 12522.06},
            {"timestamp": _utc(2026, 11, 10, 7, 5), "rxBytes": 0.5, "wifiTxRetryPackets": 0.5},
        ],
        "daily",
    )

    (row,) = rows.values()
    assert row == {"rx_bytes": 322129486, "tx_retries": 12523}
    assert all(isinstance(value, int) for value in row.values())


# --- the manager reads the site's zone ---------------------------------------------------

END = _utc(2026, 11, 10, 12, 0)


def _manager(locale: Any) -> tuple[StatsManager, MagicMock]:
    """A Network 11 manager with 5-minute WAN points across the Chicago midnight of 10 November."""
    points = [
        {"timestamp": _utc(2026, 11, 10, 5, 55), "duration": FIVE_MINUTES, "rxBytes": 1.4, "txBytes": 1},
        {"timestamp": _utc(2026, 11, 10, 6, 0), "duration": FIVE_MINUTES, "rxBytes": 2, "txBytes": 1},
    ]
    responses = {
        "/source": "MODERN",
        "/self": [{"site_id": SITE}],
        "/recent/series": [{"siteId": SITE, "series": points}],
        "/get/setting/locale": locale,
    }
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.return_value = None

    async def request(api_request):
        for prefix, answer in responses.items():
            if api_request.path.startswith(prefix):
                if isinstance(answer, BaseException):
                    raise answer
                return answer
        raise AssertionError(f"unexpected request {api_request.path}")

    connection.request = AsyncMock(side_effect=request)
    return StatsManager(connection, MagicMock()), connection


@pytest.mark.asyncio
async def test_network_stats_daily_rows_begin_at_the_site_local_midnight(monkeypatch):
    monkeypatch.setattr("unifi_core.network.managers.stats_manager._now_ms", lambda: END)
    manager, connection = _manager([{"key": "locale", "timezone": "America/Chicago"}])

    rows = await manager.get_network_stats(duration_hours=24, granularity="daily")

    assert [row["time"] for row in rows] == [_local(2026, 11, 9), _local(2026, 11, 10)]
    assert [row["wan-rx_bytes"] for row in rows] == [1, 2]
    connection._update_cache.assert_any_call("stats_site_timezone_default", "America/Chicago", timeout=3600)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "locale",
    [RequestError("settings read refused"), [{"key": "locale"}], [{"key": "locale", "timezone": "Not/AZone"}]],
    ids=["read-fails", "no-zone", "unknown-zone"],
)
async def test_daily_rows_fall_back_to_utc_when_the_site_zone_is_unavailable(monkeypatch, locale):
    monkeypatch.setattr("unifi_core.network.managers.stats_manager._now_ms", lambda: END)
    manager, _ = _manager(locale)

    rows = await manager.get_network_stats(duration_hours=24, granularity="daily")

    assert [row["time"] for row in rows] == [_utc(2026, 11, 10)]


@pytest.mark.asyncio
async def test_hourly_rows_do_not_read_the_site_zone(monkeypatch):
    monkeypatch.setattr("unifi_core.network.managers.stats_manager._now_ms", lambda: END)
    manager, connection = _manager(AssertionError("the zone is not needed for hourly rows"))

    await manager.get_network_stats(duration_hours=24, granularity="hourly")

    assert "/get/setting/locale" not in [call[0][0].path for call in connection.request.call_args_list]
