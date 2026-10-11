"""Protect evidence reads over real HTTP: uiprotect's own retry loop runs, and every attempt is charged."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from uiprotect.api import ProtectApiClient
from unifi_core.incident_evidence import BudgetKind, FailureKind, SourceOutcome
from unifi_core.protect.incident_collection import collect_protect_incident_evidence
from unifi_core.protect.managers.event_manager import EventManager
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest
from yarl import URL

WINDOW = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-08T12:59:00Z"}
PRIVATE = "fixture-private-controller-text"


async def _collect(statuses: list[int], **budget):
    """Serve ``statuses`` in turn (200 answers an empty event list) to a real uiprotect client."""
    seen: list[str] = []

    async def events(request: web.Request) -> web.Response:
        seen.append(request.method)
        status = statuses[min(len(seen), len(statuses)) - 1]
        if status == 200:
            return web.json_response([])
        return web.Response(status=status, text=PRIVATE)

    app = web.Application()
    app.router.add_get("/proxy/protect/api/events", events)
    server = TestServer(app)
    await server.start_server()
    client = ProtectApiClient("controller.invalid", 443, "fixture-user", "fixture-password", store_sessions=False)
    client._url = URL(f"http://{server.host}:{server.port}")
    client.ensure_authenticated = AsyncMock()
    client._reauthenticate = AsyncMock()
    try:
        with patch("uiprotect.api.calculate_retry_delay", return_value=0):
            evidence = await collect_protect_incident_evidence(
                EventManager(SimpleNamespace(client=client), {}), ProtectIncidentRequest(**WINDOW, **budget)
            )
    finally:
        await client.close_session()
        await server.close()
    return evidence, seen


@pytest.mark.asyncio
async def test_sdk_retries_are_refused_once_the_call_budget_is_spent() -> None:
    evidence, seen = await _collect([503, 503, 200], max_calls=1)
    assert seen == ["GET"]  # the retry was refused before it was sent
    assert evidence.budgets.usage.calls == 1 and evidence.budgets.exhausted == (BudgetKind.CALLS,)
    (source,) = evidence.sources
    assert source.outcome is SourceOutcome.NOT_ATTEMPTED and source.failure.kind is FailureKind.BUDGET_EXHAUSTED
    assert evidence.coverage_complete is False
    assert PRIVATE not in json.dumps(evidence.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_every_sdk_retry_is_charged_as_a_call() -> None:
    evidence, seen = await _collect([503, 503, 200], max_calls=5)
    assert len(seen) == evidence.budgets.usage.calls == 3
    assert evidence.sources[0].outcome is SourceOutcome.EMPTY


@pytest.mark.asyncio
async def test_the_retry_after_a_relogin_is_charged() -> None:
    evidence, seen = await _collect([401, 200], max_calls=1)
    assert seen == ["GET"] and evidence.budgets.exhausted == (BudgetKind.CALLS,)
    evidence, seen = await _collect([401, 200], max_calls=2)
    assert len(seen) == evidence.budgets.usage.calls == 2
    assert evidence.sources[0].outcome is SourceOutcome.EMPTY


@pytest.mark.asyncio
async def test_a_denied_read_is_one_charged_request_with_its_status() -> None:
    evidence, seen = await _collect([403], max_calls=5)
    assert len(seen) == evidence.budgets.usage.calls == 1
    assert evidence.sources[0].outcome is SourceOutcome.PERMISSION_DENIED
    assert evidence.sources[0].failure.http_status == 403


# --- a cold connection acquired inside the read -----------------------------------------------


class _NVR:
    """Serves the login, the bootstrap (answering ``bootstrap`` statuses in turn) and events."""

    def __init__(self, bootstrap: list[int]) -> None:
        self.bootstrap = bootstrap
        self.seen: list[str] = []
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.handle)
        self.app = app

    async def handle(self, request: web.Request) -> web.Response:
        self.seen.append(request.path)
        if request.path == "/api/auth/login":
            response = web.json_response({})
            response.set_cookie("TOKEN", "fixture-session")
            return response
        if request.path.endswith("/bootstrap"):
            served = sum(1 for path in self.seen if path.endswith("/bootstrap"))
            status = self.bootstrap[min(served, len(self.bootstrap)) - 1]
            if status != 200:
                return web.Response(status=status, text=PRIVATE)
            return web.json_response({})
        if request.path.endswith("/events"):
            return web.json_response([])
        return web.Response(status=404)

    @property
    def charged(self) -> list[str]:
        return [path for path in self.seen if path != "/api/auth/login"]


async def _collect_cold(bootstrap: list[int], monkeypatch, **budget):
    """ProtectConnectionManager.initialize for real, against a local NVR, inside the first read."""
    from unifi_core.protect.managers import connection_manager as pcm
    from unifi_core.retry import RetryPolicy

    nvr = _NVR(bootstrap)
    server = TestServer(nvr.app)
    await server.start_server()

    class LocalClient(ProtectApiClient):
        """The real client and transport, served over plain HTTP by the local NVR.

        ``update`` sends the one bootstrap request the real update starts with;
        parsing a full bootstrap needs a far larger NVR fixture.
        """

        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self._url = URL(f"http://{server.host}:{server.port}")

        async def update(self) -> None:
            await self.api_request_obj("bootstrap")

    monkeypatch.setattr(pcm, "ProtectApiClient", LocalClient)
    monkeypatch.setattr(pcm, "RetryPolicy", lambda **kw: RetryPolicy(**{**kw, "base_delay": 0}))
    connection = pcm.ProtectConnectionManager("controller.invalid", "fixture-user", "fixture-password")

    async def acquire() -> EventManager:
        if not await connection.initialize():
            raise connection.initialization_failure or ConnectionError("not connected")
        return EventManager(connection, {})

    try:
        with patch("uiprotect.api.calculate_retry_delay", return_value=0):
            evidence = await collect_protect_incident_evidence(acquire, ProtectIncidentRequest(**WINDOW, **budget))
    finally:
        await connection.close()
        await server.close()
    return evidence, nvr


@pytest.mark.asyncio
async def test_every_non_login_request_of_a_cold_connection_is_charged(monkeypatch) -> None:
    evidence, nvr = await _collect_cold([503, 200], monkeypatch, max_calls=10)
    assert "/api/auth/login" in nvr.seen
    assert nvr.charged == ["/proxy/protect/api/bootstrap", "/proxy/protect/api/bootstrap", "/proxy/protect/api/events"]
    assert evidence.budgets.usage.calls == len(nvr.charged)
    assert evidence.sources[0].outcome is SourceOutcome.EMPTY


@pytest.mark.asyncio
async def test_a_cold_connection_that_cannot_fit_the_budget_fails_closed(monkeypatch) -> None:
    evidence, nvr = await _collect_cold([200], monkeypatch, max_calls=1)
    assert nvr.charged == ["/proxy/protect/api/bootstrap"]
    assert evidence.budgets.usage.calls == 1 and evidence.budgets.exhausted == (BudgetKind.CALLS,)
    assert evidence.sources[0].outcome is SourceOutcome.NOT_ATTEMPTED and evidence.coverage_complete is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "outcome"), [(401, "auth_failed"), (403, "permission_denied")])
async def test_a_refused_bootstrap_keeps_its_category_and_no_nvr_text(monkeypatch, caplog, status, outcome) -> None:
    with caplog.at_level("DEBUG"):
        evidence, _ = await _collect_cold([status], monkeypatch, max_calls=50)
    (source,) = evidence.sources
    assert source.outcome.value == outcome
    assert source.failure.http_status == status
    assert PRIVATE not in json.dumps(evidence.model_dump(mode="json"))
    assert all(PRIVATE not in record.getMessage() and not record.exc_info for record in caplog.records)
