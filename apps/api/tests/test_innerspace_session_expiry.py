"""An InnerSpace read on the API after the console session expired, against the loopback console.

UniFi OS answers ``/api/system`` for an expired session with 200 and a public payload
without the app list. The API is the long-lived process where that happens first: the
read logs in once and succeeds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from innerspace_stub import connected, console, manager  # noqa: F401  (fixtures, by name)
from unifi_core.innerspace.managers.connection_manager import SYSTEM_PATH

from tests.innerspace_data import bootstrap, client, install

FIXTURES = Path(__file__).resolve().parents[3] / "packages/unifi-core/tests/innerspace/fixtures"


@pytest.fixture(autouse=True)
def _db_key(monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")


@pytest.mark.asyncio
async def test_a_read_after_session_expiry_logs_in_once_and_succeeds(tmp_path, connected, console):  # noqa: F811
    app, key, cid = await bootstrap(tmp_path)
    install(app, cid, connected)
    console.expire_session()
    console.reply("GET", SYSTEM_PATH, json.loads((FIXTURES / "system.json").read_text()))

    async with client(app) as c:
        response = await c.get("/v1/sites/default/innerspace/status", headers={"Authorization": f"Bearer {key}"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["running"] is True
    assert console.logins == 2
    cookies = [call.headers["Cookie"] for call in console.calls("GET", SYSTEM_PATH)]
    assert cookies == ["TOKEN=session-1", "TOKEN=session-2"]
