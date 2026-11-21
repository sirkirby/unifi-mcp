"""Server teardown logs out of the console after normal and failed startup."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from innerspace_stub import LOGOUT

from tests.unit.harness import Clock, build_manager, run_main, startup_connect_finished

pytestmark = pytest.mark.real_reconnect


@pytest.mark.parametrize("failure", [None, "registration", "transport"])
async def test_server_always_closes_its_connection(monkeypatch, console, failure):
    cm = build_manager(console.base_url, Clock())
    registration = AsyncMock(side_effect=RuntimeError("startup failure") if failure == "registration" else None)

    async def serving():
        assert await startup_connect_finished() is True
        if failure == "transport":
            raise RuntimeError("startup failure")

    if failure:
        with pytest.raises(RuntimeError, match="startup failure"):
            await run_main(monkeypatch, cm, serving, registration=registration)
    else:
        await run_main(monkeypatch, cm, serving, registration=registration)

    # A registration failure cancels the background connect before it logs in: nothing to log out.
    expected = 0 if failure == "registration" else 1
    assert cm.is_connected is False
    assert (console.logins, len(console.calls("POST", LOGOUT))) == (expected, expected)


async def test_a_failed_close_is_logged_by_class_and_keeps_the_original_error(monkeypatch, console, caplog):
    cm = build_manager(console.base_url, Clock())
    real_close = cm.close
    monkeypatch.setattr(cm, "close", AsyncMock(side_effect=OSError("close failure at 192.0.2.10")))

    async def serving():
        raise RuntimeError("startup failure")

    with pytest.raises(RuntimeError, match="startup failure"):
        await run_main(monkeypatch, cm, serving)

    assert "Failed to close the console connection: OSError" in caplog.text
    assert "192.0.2.10" not in caplog.text
    await real_close()
