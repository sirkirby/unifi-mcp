"""Reconnect through real SDK login and bootstrap decoding from a bounded read."""

import asyncio
import json
import time

import jwt
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from uiprotect import ProtectApiClient
from uiprotect.exceptions import NvrError
from unifi_core.connection_failure import ControllerConnectTimeout
from unifi_core.protect.incident_collection import collect_protect_incident_evidence
from unifi_core.protect.managers import connection_manager as pcm
from unifi_core.protect.managers.camera_manager import CameraManager
from unifi_core.protect.managers.event_manager import EventManager
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest
from yarl import URL

WINDOW = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-08T12:59:00Z"}
PRIVATE = "fixture-private-controller-text"
BOOTSTRAP = {
    "authUserId": "fixture-user",
    "accessKey": "fixture-key",
    "lastUpdateId": "fixture-update",
    "nvr": {
        "id": "fixture-nvr",
        "modelKey": "nvr",
        "version": "5.0.0",
        "timezone": "UTC",
        "hosts": ["127.0.0.1"],
        "ports": {"rtsp": 7447, "rtsps": 7441},
    },
    **{
        key: []
        for key in (
            "cameras",
            "users",
            "groups",
            "liveviews",
            "viewers",
            "lights",
            "sensors",
            "chimes",
            "bridges",
            "ringtones",
            "aiports",
        )
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "outcome"), [(401, "auth_failed"), (403, "permission_denied")])
async def test_rejected_login_is_classified_and_later_success_decodes_bootstrap(monkeypatch, caplog, status, outcome):
    login_status = status
    seen = []

    async def serve(request):
        seen.append(request.path)
        if request.path == "/api/auth/login":
            if login_status != 200:
                return web.Response(status=login_status, text=PRIVATE)
            response = web.json_response({})
            response.set_cookie(
                "TOKEN",
                jwt.encode({"exp": time.time() + 3600}, "fixture-signing-key-with-32-characters", algorithm="HS256"),
            )
            return response
        if request.path.endswith("/bootstrap"):
            return web.json_response(BOOTSTRAP)
        if request.path.endswith("/events"):
            return web.json_response([])
        return web.Response(status=404)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", serve)
    async with TestServer(app) as nvr:

        class LocalClient(ProtectApiClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs, store_sessions=False)
                self._url = URL(f"http://{nvr.host}:{nvr.port}")

        monkeypatch.setattr(pcm, "ProtectApiClient", LocalClient)
        connection = pcm.ProtectConnectionManager(
            nvr.host, "fixture-user", "fixture-password", bootstrap_refresh_seconds=0
        )
        events = EventManager(connection, {})
        request = ProtectIncidentRequest(**WINDOW, max_elapsed_ms=1_000, max_calls=2)
        try:
            assert not await connection.initialize()
            seen.clear()
            # The auth circuit holds reconnects back: the read sends nothing and
            # reports the rejected login's category and status.
            result = await collect_protect_incident_evidence(events, request)
            assert seen == []
            assert result.sources[0].outcome.value == outcome
            assert result.sources[0].failure.http_status == status
            assert result.budgets.usage.calls == 1  # the read itself, refused before sending
            # Bootstrap-based tools receive the same safe category, rather than "not initialized".
            with pytest.raises(type(connection.initialization_failure)):
                await CameraManager(connection).list_cameras()
            assert connection.support_status()["last_attempt"]["http_status"] == status

            login_status = 200
            seen.clear()
            # Past the cool-down, the read joins one reconnect attempt. The attempt
            # runs in its own task, so its login and bootstrap cost the read nothing.
            connection._clock = lambda: time.monotonic() + 3600
            result = await collect_protect_incident_evidence(events, request)
            assert result.sources[0].outcome.value == "empty" and result.coverage_complete
            assert result.budgets.usage.calls == 1
            assert seen == ["/api/auth/login", "/proxy/protect/api/bootstrap", "/proxy/protect/api/events"]
            assert connection.initialization_failure is None
            assert connection.is_connected
            assert connection.client.bootstrap.nvr.id == "fixture-nvr"
            assert await CameraManager(connection).list_cameras() == []
            assert PRIVATE not in json.dumps(result.model_dump(mode="json"))
            assert all(PRIVATE not in record.getMessage() and not record.exc_info for record in caplog.records)
        finally:
            await connection.close()


@pytest.mark.asyncio
async def test_sdk_wrapped_timeout_keeps_timeout_classification(monkeypatch):
    class TimeoutClient:
        def __init__(self, **kwargs):
            pass

        async def update(self):
            raise NvrError(PRIVATE) from TimeoutError(PRIVATE)

        async def async_disconnect_ws(self):
            pass

        async def close_session(self):
            pass

    monkeypatch.setattr(pcm, "ProtectApiClient", TimeoutClient)
    connection = pcm.ProtectConnectionManager("controller.invalid", "fixture-user", "fixture-password")
    assert not await connection.ensure_connected()
    with pytest.raises(ControllerConnectTimeout) as caught:
        connection.client
    assert caught.value.status is None and PRIVATE not in str(caught.value)


@pytest.mark.asyncio
async def test_concurrent_acquisition_owns_one_client_and_one_refresh_task(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    clients = []

    class HeldClient:
        def __init__(self, **kwargs):
            self.closed = False
            clients.append(self)

        async def update(self):
            entered.set()
            await release.wait()

        async def async_disconnect_ws(self):
            pass

        async def close_session(self):
            self.closed = True

    monkeypatch.setattr(pcm, "ProtectApiClient", HeldClient)
    connection = pcm.ProtectConnectionManager("controller.invalid", "fixture-user", "fixture-password")
    first = asyncio.create_task(connection.initialize())
    await asyncio.wait_for(entered.wait(), timeout=1)
    second = asyncio.create_task(connection.ensure_connected())
    try:
        release.set()
        assert await first
        assert await second
        assert len(clients) == 1
        assert connection._refresh_task is not None
        assert connection.client is clients[0]
    finally:
        await connection.close()
    assert clients[0].closed
