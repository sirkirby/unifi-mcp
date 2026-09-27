"""Cache identities and controller errors must not cross diagnostic boundaries."""

import logging
import traceback
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import RequestError
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.stats_manager import StatsManager
from unifi_core.network.managers.switch_manager import SwitchManager

MAC = "aa:bb:cc:dd:ee:ff"
CANARY = "private-controller-canary"


def test_cache_logs_do_not_disclose_keys_or_prefixes(caplog: pytest.LogCaptureFixture) -> None:
    connection = ConnectionManager("controller.invalid", "user", "password")
    key = f"stats_{MAC}_{CANARY}"
    with caplog.at_level(logging.DEBUG):
        assert connection.get_cached(key) is None
        generation = connection._get_cache_generation(key)
        connection._update_cache(key, {"value": 1})
        assert connection.get_cached(key) == {"value": 1}
        connection._last_cache_update[key] = 0
        assert connection.get_cached(key) is None
        connection._invalidate_cache(key)
        assert not connection._update_cache_if_current(key, {}, generation)
        connection._invalidate_cache()
    assert caplog.records
    assert MAC not in caplog.text and CANARY not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["get_client_dpi_traffic", "get_client_wifi_details", "get_client_sessions", "_get_device_stat"]
)
async def test_client_device_failure_translation_is_safe(method: str, caplog: pytest.LogCaptureFixture) -> None:
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.return_value = None
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(side_effect=RuntimeError(f"{MAC} {CANARY}"))
    manager = SwitchManager(connection) if method == "_get_device_stat" else StatsManager(connection, MagicMock())
    with caplog.at_level(logging.DEBUG), pytest.raises(RequestError) as caught:
        await getattr(manager, method)(MAC)
    connection.request.assert_awaited_once()
    rendered = "".join(traceback.format_exception(caught.value))
    assert "RuntimeError" in str(caught.value)
    assert caught.value.__suppress_context__ is True
    for value in (MAC, CANARY):
        assert value not in caplog.text
        assert value not in str(caught.value)
        assert value not in rendered
    assert all(record.exc_info is None for record in caplog.records)
